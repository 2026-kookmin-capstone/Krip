import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import text, update

from app.config import setting as setting_module
from app.domain.auth.model.user import User, UserStatus
from app.domain.chat.model.chat_room import ChatRoom, ChatRoomType
from app.domain.chat.model.chat_room_member import ChatRoomMember
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


async def _seed_room(session_factory, user_ids: list[str]) -> str:
    async with session_factory() as session:
        room = ChatRoom(
            type=ChatRoomType.GROUP,
            title="authorization-fence",
            creator_id=user_ids[0],
        )
        session.add(room)
        await session.flush()
        room_id = str(room.chat_room_id)
        session.add_all([
            ChatRoomMember(chat_room_id=room_id, user_id=user_id)
            for user_id in user_ids
        ])
        await session.commit()
    return room_id


async def test_message_fanout_holds_mutation_lock_through_delivery_scope(
    session_factory, seed_users,
):
    [user_id] = await seed_users(1)
    room_id = await _seed_room(session_factory, [user_id])
    authorization = FanoutAuthorizationService(session_factory)
    contender_reached = asyncio.Event()
    contender_acquired = asyncio.Event()

    async def contend() -> None:
        async with session_factory() as session:
            contender_reached.set()
            await session.execute(text(
                "SELECT pg_advisory_xact_lock("
                "hashtextextended('chat-message-mutation:MSG_1', 0))"
            ))
            contender_acquired.set()

    async with authorization.lock_room_delivery(
        room_id, {user_id}, message_id="MSG_1",
    ) as active_user_ids:
        assert active_user_ids == {user_id}
        contender = asyncio.create_task(contend())
        await contender_reached.wait()
        await asyncio.sleep(0)
        assert not contender_acquired.is_set()

    await asyncio.wait_for(contender, timeout=2)
    assert contender_acquired.is_set()


async def test_room_fanout_filters_member_removed_in_authoritative_db(
    session_factory, seed_users, monkeypatch,
):
    monkeypatch.setattr(setting_module.settings, "FANOUT_MODE", "in_process")
    active_id, removed_id = await seed_users(2)
    room_id = await _seed_room(session_factory, [active_id, removed_id])
    fanout = FanoutService(FanoutAuthorizationService(session_factory))
    active_ws = _ws("WS_active", active_id)
    removed_ws = _ws("WS_removed", removed_id)
    for websocket in (active_ws, removed_ws):
        fanout.register_session(websocket)
        fanout.register_ws_to_room(websocket, room_id)

    async with session_factory() as session:
        await session.execute(
            update(ChatRoomMember)
            .where(
                ChatRoomMember.chat_room_id == room_id,
                ChatRoomMember.user_id == removed_id,
            )
            .values(is_left=True)
        )
        await session.commit()

    await fanout.fan_out_to_room(room_id, {"type": "system"})

    active_ws.send_json.assert_awaited_once()
    removed_ws.send_json.assert_not_awaited()
    assert removed_ws in fanout._room_subs[room_id]


async def test_room_revocation_cannot_commit_between_authorization_and_delivery(
    session_factory, seed_users, monkeypatch,
):
    monkeypatch.setattr(setting_module.settings, "FANOUT_MODE", "in_process")
    user_id = (await seed_users(1))[0]
    room_id = await _seed_room(session_factory, [user_id])
    fanout = FanoutService(FanoutAuthorizationService(session_factory))
    websocket = _ws("WS_active", user_id)
    fanout.register_session(websocket)
    fanout.register_ws_to_room(websocket, room_id)

    send_started = asyncio.Event()
    release_send = asyncio.Event()

    async def blocked_send(_payload):
        send_started.set()
        await release_send.wait()

    websocket.send_json.side_effect = blocked_send
    delivery = asyncio.create_task(
        fanout.fan_out_to_room(room_id, {"type": "system"}),
    )
    await asyncio.wait_for(send_started.wait(), timeout=1)

    revocation_committed = asyncio.Event()

    async def revoke_member():
        async with session_factory() as session:
            await session.execute(
                update(ChatRoomMember)
                .where(
                    ChatRoomMember.chat_room_id == room_id,
                    ChatRoomMember.user_id == user_id,
                )
                .values(is_left=True)
            )
            await session.commit()
        revocation_committed.set()

    revocation = asyncio.create_task(revoke_member())
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                asyncio.shield(revocation_committed.wait()), timeout=0.1,
            )
    finally:
        release_send.set()

    await asyncio.wait_for(delivery, timeout=1)
    await asyncio.wait_for(revocation, timeout=1)
    assert revocation_committed.is_set()


async def test_user_fanout_closes_account_made_inactive_in_authoritative_db(
    session_factory, seed_users, monkeypatch,
):
    monkeypatch.setattr(setting_module.settings, "FANOUT_MODE", "in_process")
    user_id = (await seed_users(1))[0]
    fanout = FanoutService(FanoutAuthorizationService(session_factory))
    websocket = _ws("WS_stale", user_id)
    fanout.register_session(websocket)

    async with session_factory() as session:
        await session.execute(
            update(User).where(User.user_id == user_id).values(status=UserStatus.INACTIVE)
        )
        await session.commit()

    await fanout.fan_out_to_user(user_id, {"type": "unread_synced"})

    websocket.send_json.assert_not_awaited()
    websocket.close.assert_awaited_once_with(code=4001)
    assert "WS_stale" not in fanout._local_ws_by_session


async def test_account_deactivation_cannot_commit_during_user_delivery(
    session_factory, seed_users, monkeypatch,
):
    monkeypatch.setattr(setting_module.settings, "FANOUT_MODE", "in_process")
    user_id = (await seed_users(1))[0]
    fanout = FanoutService(FanoutAuthorizationService(session_factory))
    websocket = _ws("WS_active", user_id)
    fanout.register_session(websocket)

    send_started = asyncio.Event()
    release_send = asyncio.Event()

    async def blocked_send(_payload):
        send_started.set()
        await release_send.wait()

    websocket.send_json.side_effect = blocked_send
    delivery = asyncio.create_task(
        fanout.fan_out_to_user(user_id, {"type": "unread_synced"}),
    )
    await asyncio.wait_for(send_started.wait(), timeout=1)

    deactivation_committed = asyncio.Event()

    async def deactivate_account():
        async with session_factory() as session:
            await session.execute(
                update(User)
                .where(User.user_id == user_id)
                .values(status=UserStatus.INACTIVE)
            )
            await session.commit()
        deactivation_committed.set()

    deactivation = asyncio.create_task(deactivate_account())
    try:
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                asyncio.shield(deactivation_committed.wait()), timeout=0.1,
            )
    finally:
        release_send.set()

    await asyncio.wait_for(delivery, timeout=1)
    await asyncio.wait_for(deactivation, timeout=1)
    assert deactivation_committed.is_set()


async def test_unread_delivery_scope_blocks_account_deactivation_commit(
    session_factory, seed_users,
):
    user_id = (await seed_users(1))[0]
    deactivation_committed = asyncio.Event()

    class AppContainer:
        def uow(self):
            return session_factory()

    websocket = MagicMock()
    websocket.app.container = AppContainer()

    async def deactivate_account():
        async with session_factory() as session:
            await session.execute(
                update(User)
                .where(User.user_id == user_id)
                .values(status=UserStatus.INACTIVE)
            )
            await session.commit()
        deactivation_committed.set()

    async with _lock_active_unread_rooms(websocket, user_id, set()) as active_rooms:
        assert active_rooms == set()
        deactivation = asyncio.create_task(deactivate_account())
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                asyncio.shield(deactivation_committed.wait()), timeout=0.1,
            )

    await asyncio.wait_for(deactivation, timeout=1)
    assert deactivation_committed.is_set()
