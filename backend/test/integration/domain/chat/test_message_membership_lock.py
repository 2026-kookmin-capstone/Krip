import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.database.session import UnitOfWork
from app.domain.chat.model.chat_room import ChatRoom, ChatRoomType
from app.domain.chat.model.chat_room_member import ChatRoomMember
from app.domain.chat.repository.chat_member import ChatRoomMemberRepository
from app.domain.chat.repository.chat_room import ChatRoomRepository
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
    seed_users, session_factory, monkeypatch,
):
    user_id, _, _ = await seed_users(3)
    async with session_factory() as session:
        room = ChatRoom(type=ChatRoomType.GROUP, title="lock-order", creator_id=user_id)
        session.add(room)
        await session.flush()
        room_id = str(room.chat_room_id)
        session.add(ChatRoomMember(chat_room_id=room_id, user_id=user_id))
        await session.commit()

    member_locked = asyncio.Event()
    room_lookup_done = asyncio.Event()
    original_share = ChatRoomMemberRepository.is_active_member_for_share
    original_find = ChatRoomRepository.find_by_id
    original_find_for_update = ChatRoomRepository.find_by_id_for_update

    async def coordinated_share(repo, target_room_id, target_user_id):
        result = await original_share(repo, target_room_id, target_user_id)
        member_locked.set()
        await room_lookup_done.wait()
        return result

    async def coordinated_find(repo, target_room_id):
        await member_locked.wait()
        result = await original_find(repo, target_room_id)
        room_lookup_done.set()
        return result

    async def coordinated_find_for_update(repo, target_room_id):
        await member_locked.wait()
        result = await original_find_for_update(repo, target_room_id)
        room_lookup_done.set()
        return result

    monkeypatch.setattr(
        ChatRoomMemberRepository,
        "is_active_member_for_share",
        coordinated_share,
    )
    monkeypatch.setattr(ChatRoomRepository, "find_by_id", coordinated_find)
    monkeypatch.setattr(
        ChatRoomRepository,
        "find_by_id_for_update",
        coordinated_find_for_update,
    )

    async def send_db_part():
        async with session_factory() as session:
            async with session.begin():
                member_repo = ChatRoomMemberRepository(session)
                assert await member_repo.is_active_member_for_share(room_id, user_id)
                await ChatRoomRepository(session).update_last_message_if_greater(
                    chat_room_id=room_id,
                    message_id="MSG_lock_order",
                    server_seq=1,
                    at=datetime.now(timezone.utc),
                )

    async def leave_db_part():
        service = RoomService(
            uow=UnitOfWork(session_factory),
            fanout_service=None,
            message_service=None,
        )
        await service._leave_room_tx(me_id=user_id, room_id=room_id)

    await asyncio.wait_for(
        asyncio.gather(send_db_part(), leave_db_part()),
        timeout=5,
    )
