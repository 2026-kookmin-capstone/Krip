import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.database.session import UnitOfWork
from app.domain.chat.model.chat_message import MessageType
from app.domain.chat.model.chat_room import ChatRoom, ChatRoomType
from app.domain.chat.model.chat_room_member import ChatRoomMember
from app.domain.chat.repository.chat_member import ChatRoomMemberRepository
from app.domain.chat.repository.chat_room import ChatRoomRepository
from app.domain.chat.service.message import MessageService
from app.domain.chat.service.room import RoomService


pytestmark = pytest.mark.integration


async def test_send_membership_lock_blocks_concurrent_leave_update(
    seed_users, session_factory,
):
    user_id, _, _ = await seed_users(3)
    async with session_factory() as session:
        room = ChatRoom(type=ChatRoomType.GROUP, title="lock", creator_id=user_id)
        session.add(room)
        await session.flush()
        room_id = str(room.chat_room_id)
        session.add(ChatRoomMember(chat_room_id=room_id, user_id=user_id))
        await session.commit()

    async with session_factory() as send_session:
        assert await ChatRoomMemberRepository(send_session).is_active_member_for_share(
            room_id, user_id,
        )

        async with session_factory() as leave_session:
            probe = (
                select(ChatRoomMember)
                .where(
                    ChatRoomMember.chat_room_id == room_id,
                    ChatRoomMember.user_id == user_id,
                )
                .with_for_update(nowait=True)
            )
            with pytest.raises(DBAPIError):
                await leave_session.execute(probe)


async def test_recovery_membership_lock_blocks_concurrent_leave_update(
    seed_users, session_factory,
):
    user_id, _, _ = await seed_users(3)
    async with session_factory() as session:
        room = ChatRoom(type=ChatRoomType.GROUP, title="recovery-lock", creator_id=user_id)
        session.add(room)
        await session.flush()
        room_id = str(room.chat_room_id)
        session.add(ChatRoomMember(chat_room_id=room_id, user_id=user_id))
        await session.commit()

    async with session_factory() as recovery_session:
        last_reads = await ChatRoomMemberRepository(recovery_session).find_last_read_seqs(
            user_id,
            for_share=True,
        )
        assert last_reads == {room_id: 0}

        async with session_factory() as leave_session:
            probe = (
                select(ChatRoomMember)
                .where(
                    ChatRoomMember.chat_room_id == room_id,
                    ChatRoomMember.user_id == user_id,
                )
                .with_for_update(nowait=True)
            )
            with pytest.raises(DBAPIError):
                await leave_session.execute(probe)


async def test_send_and_leave_lock_order_does_not_deadlock(
    seed_users,
    session_factory,
    monkeypatch,
    chat_fanout_stub,
    chat_fcm_stub,
    patch_external_clients,
):
    user_id, _, _ = await seed_users(3)
    async with session_factory() as session:
        room = ChatRoom(type=ChatRoomType.GROUP, title="lock-order", creator_id=user_id)
        session.add(room)
        await session.flush()
        room_id = str(room.chat_room_id)
        session.add(ChatRoomMember(chat_room_id=room_id, user_id=user_id))
        await session.commit()

    room_locked = asyncio.Event()
    member_locked = asyncio.Event()
    original_room_lock = ChatRoomRepository.find_by_id_for_update
    original_member_lock = ChatRoomMemberRepository.find_for_update

    async def coordinated_room_lock(repo, target_room_id):
        result = await original_room_lock(repo, target_room_id)
        room_locked.set()
        await member_locked.wait()
        return result

    async def coordinated_member_lock(repo, target_room_id, target_user_id):
        await room_locked.wait()
        result = await original_member_lock(repo, target_room_id, target_user_id)
        member_locked.set()
        return result

    monkeypatch.setattr(
        ChatRoomRepository,
        "find_by_id_for_update",
        coordinated_room_lock,
    )
    monkeypatch.setattr(
        ChatRoomMemberRepository,
        "find_for_update",
        coordinated_member_lock,
    )

    async def send():
        service = MessageService(
            uow=UnitOfWork(session_factory),
            fanout_service=chat_fanout_stub,
            fcm_service_factory=lambda: chat_fcm_stub,
        )
        return await service.send_message(
            sender_user_id=user_id,
            sender_session_id="WS_lock_order",
            room_id=room_id,
            client_msg_id="CLIENT_lock_order",
            msg_type=MessageType.TEXT,
            content="race",
        )

    async def leave_db_part():
        service = RoomService(
            uow=UnitOfWork(session_factory),
            fanout_service=None,
            message_service=None,
        )
        await service._leave_room_tx(me_id=user_id, room_id=room_id)

    send_task = asyncio.create_task(send())
    await asyncio.wait_for(room_locked.wait(), timeout=2)
    leave_task = asyncio.create_task(leave_db_part())
    results = await asyncio.wait_for(
        asyncio.gather(send_task, leave_task, return_exceptions=True),
        timeout=5,
    )
    assert isinstance(results[0], PermissionError)
    assert not isinstance(results[1], BaseException)
