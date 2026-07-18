import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import update

from app.config import setting as setting_module
from app.domain.chat.model.chat_room import ChatRoom, ChatRoomType
from app.domain.chat.model.chat_room_member import ChatRoomMember
from app.domain.chat.repository.chat_member import ChatRoomMemberRepository
from app.domain.chat.router.ws import _lock_active_unread_rooms
from app.domain.chat.service.fanout import FanoutAuthorizationService, FanoutService


pytestmark = pytest.mark.integration


def _ws(session_id: str, user_id: str) -> MagicMock:
    websocket = MagicMock()
    websocket.session_id = session_id
    websocket.user_id = user_id
    websocket.subscribed_rooms = set()
    websocket.send_json = AsyncMock()
    websocket.close = AsyncMock()
    return websocket


async def test_subscription_reconciliation_serializes_reinvite_and_stale_unsubscribe(
    session_factory, seed_users, monkeypatch,
):
    monkeypatch.setattr(setting_module.settings, "FANOUT_MODE", "in_process")
    user_id = (await seed_users(1))[0]
    async with session_factory() as session:
        room = ChatRoom(
            type=ChatRoomType.GROUP,
            title="subscription-fence",
            creator_id=user_id,
        )
        session.add(room)
        await session.flush()
        room_id = str(room.chat_room_id)
        session.add(ChatRoomMember(chat_room_id=room_id, user_id=user_id))
        await session.commit()
        await session.execute(
            update(ChatRoomMember)
            .where(
                ChatRoomMember.chat_room_id == room_id,
                ChatRoomMember.user_id == user_id,
            )
            .values(is_left=True),
        )
        await session.commit()

    authorization = FanoutAuthorizationService(session_factory)
    fanout = FanoutService(authorization)
    websocket = _ws("WS_1", user_id)
    fanout.register_session(websocket)
    fanout.register_ws_to_room(websocket, room_id)
    reinvite_started = asyncio.Event()
    reinvite_committed = asyncio.Event()

    async def reinvite() -> None:
        async with session_factory() as session:
            reinvite_started.set()
            await session.execute(
                update(ChatRoomMember)
                .where(
                    ChatRoomMember.chat_room_id == room_id,
                    ChatRoomMember.user_id == user_id,
                )
                .values(is_left=False),
            )
            await session.commit()
        reinvite_committed.set()

    async with authorization.lock_room_subscription(room_id, user_id) as is_active:
        assert not is_active
        task = asyncio.create_task(reinvite())
        await asyncio.wait_for(reinvite_started.wait(), timeout=1)
        await asyncio.sleep(0.05)
        assert not reinvite_committed.is_set()
        fanout._local_unsubscribe_user_from_room(user_id, room_id)

    await asyncio.wait_for(task, timeout=1)
    assert reinvite_committed.is_set()

    await fanout.dispatch_envelope({
        "op": "unsubscribe", "user_id": user_id, "room_id": room_id,
    })
    assert websocket in fanout._room_subs[room_id]


async def test_unread_membership_lock_blocks_leave_commit(
    session_factory, seed_users, monkeypatch,
):
    monkeypatch.setattr(setting_module.settings, "FANOUT_MODE", "in_process")
    user_id = (await seed_users(1))[0]
    async with session_factory() as session:
        room = ChatRoom(
            type=ChatRoomType.GROUP,
            title="unread-fence",
            creator_id=user_id,
        )
        session.add(room)
        await session.flush()
        room_id = str(room.chat_room_id)
        session.add(ChatRoomMember(chat_room_id=room_id, user_id=user_id))
        await session.commit()

    class AppContainer:
        def uow(self):
            return session_factory()

    websocket = MagicMock()
    websocket.app.container = AppContainer()
    leave_started = asyncio.Event()
    leave_committed = asyncio.Event()

    async def leave() -> None:
        async with session_factory() as session:
            leave_started.set()
            await session.execute(
                update(ChatRoomMember)
                .where(
                    ChatRoomMember.chat_room_id == room_id,
                    ChatRoomMember.user_id == user_id,
                )
                .values(is_left=True),
            )
            await session.commit()
        leave_committed.set()

    async with _lock_active_unread_rooms(
        websocket, user_id, {room_id},
    ) as active_room_ids:
        assert active_room_ids == {room_id}
        task = asyncio.create_task(leave())
        await asyncio.wait_for(leave_started.wait(), timeout=1)
        await asyncio.sleep(0.05)
        assert not leave_committed.is_set()

    await asyncio.wait_for(task, timeout=1)
    assert leave_committed.is_set()


async def test_join_timeline_membership_lock_blocks_leave_commit(
    session_factory, seed_users,
):
    user_id = (await seed_users(1))[0]
    async with session_factory() as session:
        room = ChatRoom(
            type=ChatRoomType.GROUP,
            title="join-timeline-fence",
            creator_id=user_id,
        )
        session.add(room)
        await session.flush()
        room_id = str(room.chat_room_id)
        session.add(ChatRoomMember(chat_room_id=room_id, user_id=user_id))
        await session.commit()

    leave_started = asyncio.Event()
    leave_committed = asyncio.Event()

    async def leave() -> None:
        async with session_factory() as session:
            leave_started.set()
            await session.execute(
                update(ChatRoomMember)
                .where(
                    ChatRoomMember.chat_room_id == room_id,
                    ChatRoomMember.user_id == user_id,
                )
                .values(is_left=True),
            )
            await session.commit()
        leave_committed.set()

    async with session_factory() as session:
        active_ids = await ChatRoomMemberRepository(
            session,
        ).lock_active_member_user_ids(room_id, {user_id})
        assert active_ids == {user_id}
        task = asyncio.create_task(leave())
        await asyncio.wait_for(leave_started.wait(), timeout=1)
        await asyncio.sleep(0.05)
        assert not leave_committed.is_set()

    await asyncio.wait_for(task, timeout=1)
    assert leave_committed.is_set()
