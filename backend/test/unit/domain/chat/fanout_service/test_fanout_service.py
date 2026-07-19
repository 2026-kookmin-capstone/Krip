"""FanoutService 단위 테스트 — in-process dict fan-out 의 핵심 동작 검증."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.chat.service import fanout as fanout_module
from test.unit.domain.chat.fanout_service.conftest import authorization_scope, make_ws


def _allow_all_authorization() -> MagicMock:
    authorization = MagicMock()
    authorization.lock_room_delivery = MagicMock(
        side_effect=lambda _room_id, user_ids, **_kwargs: authorization_scope(set(user_ids)),
    )
    authorization.lock_user_delivery = MagicMock(
        side_effect=lambda _user_id: authorization_scope(True),
    )
    authorization.lock_room_subscription = MagicMock(
        side_effect=lambda _room_id, _user_id: authorization_scope(True),
    )
    authorization.prepare_current_message_event = AsyncMock(return_value=True)
    return authorization


@pytest.mark.unit
async def test_forced_close_is_registered_with_application_supervisor(monkeypatch):
    supervisor = MagicMock()
    supervisor.spawn.side_effect = lambda coroutine, **_kwargs: coroutine.close()
    monkeypatch.setattr(fanout_module, "background_tasks", supervisor, raising=False)

    fanout_module.FanoutService._spawn_close(make_ws("WS_close", "U_A"))

    supervisor.spawn.assert_called_once()
    assert supervisor.spawn.call_args.kwargs["name"] == "chat-ws-close-WS_close"


@pytest.mark.unit
class TestRegister:
    def test_register_session_adds_to_user_subs(self, fanout):
        ws = make_ws("WS_1", "U_A")
        fanout.register_session(ws)

        assert ws in fanout._user_subs["U_A"]
        assert fanout._local_ws_by_session["WS_1"] is ws

    def test_register_ws_to_room_adds_to_room_subs_and_back_index(self, fanout):
        ws = make_ws("WS_1", "U_A")
        fanout.register_ws_to_room(ws, "CR_1")

        assert ws in fanout._room_subs["CR_1"]
        assert "CR_1" in ws.subscribed_rooms


@pytest.mark.unit
class TestUnregister:
    def test_unregister_clears_all_dicts(self, fanout):
        ws_a = make_ws("WS_a", "U_A")
        ws_b = make_ws("WS_b", "U_B")

        fanout.register_session(ws_a)
        fanout.register_session(ws_b)
        fanout.register_ws_to_room(ws_a, "CR_1")
        fanout.register_ws_to_room(ws_b, "CR_1")
        fanout.register_ws_to_room(ws_a, "CR_2")
        fanout._latest_room_message_seq["CR_2"] = 1

        fanout.unregister_ws(ws_a)

        assert "WS_a" not in fanout._local_ws_by_session
        assert "WS_b" in fanout._local_ws_by_session
        assert "U_A" not in fanout._user_subs
        assert ws_b in fanout._user_subs["U_B"]
        assert ws_a not in fanout._room_subs["CR_1"]
        assert ws_b in fanout._room_subs["CR_1"]
        assert "CR_2" not in fanout._room_subs
        assert "CR_2" not in fanout._latest_room_message_seq

    def test_unregister_tolerates_missing_attributes(self, fanout):
        """속성이 없는 WS 라도 예외 없이 지나가야 한다 (방어적)."""
        ws = make_ws("WS_1", "U_A")
        del ws.subscribed_rooms
        fanout.register_session(ws)
        fanout.unregister_ws(ws)

        assert "WS_1" not in fanout._local_ws_by_session


@pytest.mark.unit
class TestFanOutToRoom:
    async def test_empty_local_room_skips_authorization_query(self, fanout):
        fanout._authorization.lock_room_delivery.reset_mock()

        await fanout.fan_out_to_room("CR_empty", {"type": "message.new"})

        fanout._authorization.lock_room_delivery.assert_not_called()

    async def test_authorization_db_failure_drops_room_event(self, fanout):
        websocket = make_ws("WS_A", "U_A")
        fanout.register_session(websocket)
        fanout.register_ws_to_room(websocket, "CR_1")
        fanout._authorization.lock_room_delivery = MagicMock(
            return_value=authorization_scope(error=RuntimeError("db down")),
        )

        with pytest.raises(RuntimeError, match="db down"):
            await fanout.fan_out_to_room("CR_1", {"type": "message.new"})

        websocket.send_json.assert_not_awaited()

    async def test_drops_delivery_without_mutating_subscription_when_membership_is_revoked(
        self, fanout,
    ):
        removed = make_ws("WS_removed", "U_REMOVED")
        active = make_ws("WS_active", "U_ACTIVE")
        for ws in (removed, active):
            fanout.register_session(ws)
            fanout.register_ws_to_room(ws, "CR_1")

        fanout._authorization = MagicMock()
        fanout._authorization.lock_room_delivery = MagicMock(
            return_value=authorization_scope({"U_ACTIVE"}),
        )
        fanout._authorization.prepare_current_message_event = AsyncMock(return_value=True)

        await fanout.fan_out_to_room("CR_1", {"type": "message.new"})

        removed.send_json.assert_not_awaited()
        active.send_json.assert_awaited_once()
        assert removed in fanout._room_subs["CR_1"]
        assert "CR_1" in removed.subscribed_rooms

    async def test_skips_sender_session(self, fanout):
        """발신 세션은 skip, 다른 세션 (같은 유저 다른 세션 / 다른 유저) 는 수신."""
        phone = make_ws("WS_phone", "U_A")
        pc = make_ws("WS_pc", "U_A")
        bob = make_ws("WS_bob", "U_B")
        for ws in (phone, pc, bob):
            fanout.register_session(ws)
            fanout.register_ws_to_room(ws, "CR_1")

        await fanout.fan_out_to_room(
            "CR_1",
            {"type": "message.new", "sender_session_id": "WS_phone"},
        )

        phone.send_json.assert_not_called()
        pc.send_json.assert_awaited_once()
        bob.send_json.assert_awaited_once()

    async def test_no_recipients_noop(self, fanout):
        """빈 방에 발행해도 예외 없이 통과."""
        await fanout.fan_out_to_room("CR_empty", {"type": "message.new", "sender_session_id": "?"})

    async def test_missing_sender_session_id_delivers_to_all(self, fanout):
        """payload 에 sender_session_id 없으면 전원에게 전달 (시스템 메시지 등의 경우)."""
        a = make_ws("WS_a", "U_A")
        b = make_ws("WS_b", "U_B")
        for ws in (a, b):
            fanout.register_session(ws)
            fanout.register_ws_to_room(ws, "CR_1")

        await fanout.fan_out_to_room("CR_1", {"type": "system"})

        a.send_json.assert_awaited_once()
        b.send_json.assert_awaited_once()

    async def test_message_delivery_holds_its_mutation_lock_through_broadcast(
        self, fanout,
    ):
        websocket = make_ws("WS_A", "U_A")
        fanout.register_session(websocket)
        fanout.register_ws_to_room(websocket, "CR_1")

        await fanout.fan_out_to_room("CR_1", {
            "type": "message.new",
            "message": {"message_id": "MSG_1"},
        })

        assert fanout._authorization.lock_room_delivery.call_args.kwargs == {
            "message_id": "MSG_1",
        }
        websocket.send_json.assert_awaited_once()

    async def test_older_edit_arriving_after_delete_is_dropped(self, fanout):
        websocket = make_ws("WS_A", "U_A")
        fanout.register_session(websocket)
        fanout.register_ws_to_room(websocket, "CR_1")
        delivered = []

        async def send(payload):
            delivered.append(payload["type"])

        fanout._authorization.prepare_current_message_event.side_effect = [True, False]
        websocket.send_json.side_effect = send
        await fanout.fan_out_to_room("CR_1", {
            "type": "message.deleted",
            "message_id": "MSG_1",
            "deleted_at": "2026-07-15T00:00:02+00:00",
        })
        await fanout.fan_out_to_room("CR_1", {
            "type": "message.updated",
            "message_id": "MSG_1",
            "edited_at": "2026-07-15T00:00:01+00:00",
        })

        assert delivered == ["message.deleted"]

    async def test_delayed_lower_message_seq_is_delivered_for_client_merge(self, fanout):
        websocket = make_ws("WS_A", "U_A")
        fanout.register_session(websocket)
        fanout.register_ws_to_room(websocket, "CR_1")
        delivered = []

        async def send(payload):
            delivered.append(payload["message"]["server_seq"])

        websocket.send_json.side_effect = send
        await fanout.fan_out_to_room("CR_1", {
            "type": "message.new",
            "message": {
                "message_id": "MSG_2",
                "server_seq": 2,
                "created_at": "2026-07-15T00:00:02+00:00",
            },
        })
        await fanout.fan_out_to_room("CR_1", {
            "type": "message.new",
            "message": {
                "message_id": "MSG_1",
                "server_seq": 1,
                "created_at": "2026-07-15T00:00:01+00:00",
            },
        })

        assert delivered == [2, 1]

    async def test_same_room_socket_delivery_is_serialized(self, fanout):
        websocket = make_ws("WS_A", "U_A")
        fanout.register_session(websocket)
        fanout.register_ws_to_room(websocket, "CR_1")
        first_send_started = asyncio.Event()
        release_first_send = asyncio.Event()
        second_send_started = asyncio.Event()
        delivered = []

        async def send(payload):
            if payload["type"] == "message.updated":
                first_send_started.set()
                await release_first_send.wait()
            else:
                second_send_started.set()
            delivered.append(payload["type"])

        websocket.send_json.side_effect = send
        edit = asyncio.create_task(fanout.fan_out_to_room("CR_1", {
            "type": "message.updated",
            "message_id": "MSG_1",
            "edited_at": "2026-07-15T00:00:01+00:00",
        }))
        await asyncio.wait_for(first_send_started.wait(), timeout=1)

        delete = asyncio.create_task(fanout.fan_out_to_room("CR_1", {
            "type": "message.deleted",
            "message_id": "MSG_1",
            "deleted_at": "2026-07-15T00:00:02+00:00",
        }))
        try:
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(second_send_started.wait()), timeout=0.05,
                )
        finally:
            release_first_send.set()

        await asyncio.wait_for(asyncio.gather(edit, delete), timeout=1)
        assert delivered == ["message.updated", "message.deleted"]

    async def test_independent_message_mutations_do_not_suppress_each_other(self, fanout):
        websocket = make_ws("WS_A", "U_A")
        fanout.register_session(websocket)
        fanout.register_ws_to_room(websocket, "CR_1")

        await fanout.fan_out_to_room("CR_1", {
            "type": "message.updated",
            "message_id": "MSG_A",
            "edited_at": "2026-07-15T00:00:02+00:00",
        })
        await fanout.fan_out_to_room("CR_1", {
            "type": "message.updated",
            "message_id": "MSG_B",
            "edited_at": "2026-07-15T00:00:01+00:00",
        })

        assert [call.args[0]["message_id"] for call in websocket.send_json.await_args_list] == [
            "MSG_A", "MSG_B",
        ]


@pytest.mark.unit
class TestFanOutToUser:
    async def test_drops_delivery_and_unregisters_inactive_account(self, fanout):
        stale = make_ws("WS_stale", "U_INACTIVE")
        fanout.register_session(stale)
        fanout.register_ws_to_room(stale, "CR_1")
        fanout._authorization.lock_user_delivery = MagicMock(
            return_value=authorization_scope(False),
        )

        await fanout.fan_out_to_user("U_INACTIVE", {"type": "unread_synced"})

        stale.send_json.assert_not_awaited()
        assert "WS_stale" not in fanout._local_ws_by_session
        assert "U_INACTIVE" not in fanout._user_subs
        assert stale not in fanout._room_subs["CR_1"]

    async def test_delivers_to_all_user_sessions(self, fanout):
        phone = make_ws("WS_phone", "U_A")
        pc = make_ws("WS_pc", "U_A")
        bob = make_ws("WS_bob", "U_B")
        for ws in (phone, pc, bob):
            fanout.register_session(ws)

        await fanout.fan_out_to_user("U_A", {"type": "room_joined", "room_id": "CR_1"})

        phone.send_json.assert_awaited_once()
        pc.send_json.assert_awaited_once()
        bob.send_json.assert_not_called()

    async def test_no_sessions_noop(self, fanout):
        await fanout.fan_out_to_user("U_ghost", {"type": "room_joined", "room_id": "?"})


@pytest.mark.unit
class TestFanOutToSession:
    async def test_delivers_to_target_only(self, fanout):
        phone = make_ws("WS_phone", "U_A")
        pc = make_ws("WS_pc", "U_A")
        for ws in (phone, pc):
            fanout.register_session(ws)

        await fanout.fan_out_to_session("WS_phone", {"type": "session_revoked", "session_id": "WS_phone"})

        phone.send_json.assert_awaited_once()
        pc.send_json.assert_not_called()
        phone.close.assert_awaited_once()
        assert "WS_phone" not in fanout._local_ws_by_session
        pc.close.assert_not_called()

    async def test_missing_session_silent(self, fanout):
        """이미 close 된 세션은 dict 에서 pop 된 상태 — 조용히 무시."""
        await fanout.fan_out_to_session("WS_ghost", {"type": "session_revoked", "session_id": "?"})


@pytest.mark.unit
class TestErrorTolerance:
    async def test_one_ws_failure_does_not_block_others(self, fanout):
        """한 WS 가 send 실패해도 다른 WS 는 영향 없이 수신."""
        ok = make_ws("WS_ok", "U_A")
        boom = make_ws("WS_boom", "U_B")
        boom.send_json.side_effect = RuntimeError("connection closed")
        for ws in (ok, boom):
            fanout.register_session(ws)
            fanout.register_ws_to_room(ws, "CR_1")

        await fanout.fan_out_to_room("CR_1", {"type": "system"})
        ok.send_json.assert_awaited_once()

    async def test_slow_ws_times_out_and_is_unregistered(self, fanout, monkeypatch):
        """정체된 클라이언트(send 무한 대기)는 타임아웃 후 dead 처리 — 나머지는 정상 수신."""
        import asyncio

        from app.domain.chat.service import fanout as fanout_module

        monkeypatch.setattr(fanout_module, "_SEND_TIMEOUT_SECONDS", 0.01)

        slow = make_ws("WS_slow", "U_A")
        fast = make_ws("WS_fast", "U_B")

        async def _hang(payload):
            await asyncio.sleep(1)

        slow.send_json = AsyncMock(side_effect=_hang)
        for ws in (slow, fast):
            fanout.register_session(ws)
            fanout.register_ws_to_room(ws, "CR_1")

        await fanout.fan_out_to_room("CR_1", {"type": "message.new"})

        fast.send_json.assert_awaited_once()
        assert "WS_slow" not in fanout._local_ws_by_session
        assert fast in fanout._room_subs["CR_1"]

    async def test_cancelled_send_is_treated_as_dead_socket(self, fanout, monkeypatch):
        websocket = make_ws("WS_cancelled", "U_A")
        fanout.register_session(websocket)
        fanout.register_ws_to_room(websocket, "CR_1")
        websocket.send_json.side_effect = asyncio.CancelledError
        spawn_close = MagicMock()
        monkeypatch.setattr(fanout, "_spawn_close", spawn_close)

        await fanout.fan_out_to_room("CR_1", {"type": "system"})

        assert websocket not in fanout._room_subs["CR_1"]
        spawn_close.assert_called_once_with(websocket)


@pytest.mark.unit
class TestFanoutModeGuard:
    def test_unsupported_mode_raises(self, monkeypatch):
        """미지원 모드로 잘못 기동하면 생성자에서 NotImplementedError.

        지원 모드(`in_process` / `node_channel`) 외 값을 env 로 흘려보낸 경우 — 오타 등.
        """
        from app.config import setting as setting_module
        monkeypatch.setattr(setting_module.settings, "FANOUT_MODE", "broken_mode")

        from app.domain.chat.service.fanout import FanoutService
        with pytest.raises(NotImplementedError, match="미지원"):
            FanoutService(authorization_service=_allow_all_authorization())

    def test_node_channel_mode_initializes(self, monkeypatch):
        """`node_channel` 모드로 부팅하면 생성자 통과 (디스패처/레지스트리 와이어링은 lifespan 책임)."""
        from app.config import setting as setting_module
        monkeypatch.setattr(setting_module.settings, "FANOUT_MODE", "node_channel")

        from app.domain.chat.service.fanout import FanoutService
        svc = FanoutService(authorization_service=_allow_all_authorization())
        assert svc._mode == "node_channel"
        assert svc._room_subs == {}
        assert svc._user_subs == {}
        assert svc._local_ws_by_session == {}


@pytest.mark.unit
class TestNodeChannelDispatch:
    """`node_channel` 모드에서 디스패처가 받은 envelope 이 로컬 전달 경로로 들어가는지 검증.

    publish 자체는 Redis 의존이라 mock 으로 격리된 별도 통합 테스트에서 다루고, 여기선
    `dispatch_envelope` 가 모드 무관 로컬 dict 를 정확히 구동하는지에 집중.
    """

    @pytest.fixture
    def node_fanout(self, monkeypatch):
        from app.config import setting as setting_module
        monkeypatch.setattr(setting_module.settings, "FANOUT_MODE", "node_channel")
        from app.domain.chat.service.fanout import FanoutService
        return FanoutService(authorization_service=_allow_all_authorization())

    async def test_dispatch_room_envelope_delivers_locally(self, node_fanout):
        ws = make_ws("WS_a", "U_A")
        node_fanout.register_session(ws)
        node_fanout.register_ws_to_room(ws, "CR_1")

        await node_fanout.dispatch_envelope({
            "op": "room",
            "room_id": "CR_1",
            "payload": {"type": "message.new", "sender_session_id": "WS_other"},
        })

        ws.send_json.assert_awaited_once()

    async def test_stale_unsubscribe_is_ignored_after_membership_reactivation(
        self, node_fanout,
    ):
        ws = make_ws("WS_a", "U_A")
        node_fanout.register_session(ws)
        node_fanout.register_ws_to_room(ws, "CR_1")
        node_fanout._authorization.lock_room_subscription = MagicMock(
            return_value=authorization_scope(True),
        )

        await node_fanout.dispatch_envelope({
            "op": "unsubscribe", "user_id": "U_A", "room_id": "CR_1",
        })

        assert ws in node_fanout._room_subs["CR_1"]

    async def test_delayed_member_removed_is_dropped_after_reinvite(self, node_fanout):
        ws = make_ws("WS_a", "U_A")
        node_fanout.register_session(ws)
        node_fanout._authorization.lock_room_subscription = MagicMock(
            return_value=authorization_scope(True),
        )

        await node_fanout.dispatch_envelope({
            "op": "member_removed", "user_id": "U_A", "room_id": "CR_1",
        })

        ws.send_json.assert_not_awaited()

    async def test_current_member_removed_delivers_canonical_room_left(self, node_fanout):
        ws = make_ws("WS_a", "U_A")
        node_fanout.register_session(ws)
        node_fanout._authorization.lock_room_subscription = MagicMock(
            return_value=authorization_scope(False),
        )

        await node_fanout.dispatch_envelope({
            "op": "member_removed", "user_id": "U_A", "room_id": "CR_1",
        })

        ws.send_json.assert_awaited_once_with({
            "type": "room_left", "room_id": "CR_1",
        })

    async def test_delayed_member_joined_is_dropped_after_revocation(self, node_fanout):
        ws = make_ws("WS_a", "U_A")
        node_fanout.register_session(ws)
        node_fanout._authorization.lock_room_subscription = MagicMock(
            return_value=authorization_scope(False),
        )

        await node_fanout.dispatch_envelope({
            "op": "member_joined", "user_id": "U_A", "room_id": "CR_1",
        })

        ws.send_json.assert_not_awaited()

    async def test_current_member_joined_delivers_canonical_room_joined(self, node_fanout):
        ws = make_ws("WS_a", "U_A")
        node_fanout.register_session(ws)
        node_fanout._authorization.lock_room_subscription = MagicMock(
            return_value=authorization_scope(True),
        )

        await node_fanout.dispatch_envelope({
            "op": "member_joined", "user_id": "U_A", "room_id": "CR_1",
        })

        ws.send_json.assert_awaited_once_with({
            "type": "room_joined", "room_id": "CR_1",
        })

    async def test_stale_subscribe_is_ignored_after_membership_revocation(
        self, node_fanout,
    ):
        ws = make_ws("WS_a", "U_A")
        node_fanout.register_session(ws)
        node_fanout._authorization.lock_room_subscription = MagicMock(
            return_value=authorization_scope(False),
        )

        await node_fanout.dispatch_envelope({
            "op": "subscribe", "user_id": "U_A", "room_id": "CR_1",
        })

        assert "CR_1" not in node_fanout._room_subs

    async def test_dispatch_user_envelope_delivers_to_all_user_sessions(self, node_fanout):
        phone = make_ws("WS_phone", "U_A")
        pc = make_ws("WS_pc", "U_A")
        for ws in (phone, pc):
            node_fanout.register_session(ws)

        await node_fanout.dispatch_envelope({
            "op": "user",
            "user_id": "U_A",
            "payload": {"type": "room_joined", "room_id": "CR_1"},
        })

        phone.send_json.assert_awaited_once()
        pc.send_json.assert_awaited_once()

    async def test_dispatch_session_envelope_delivers_to_target_only(self, node_fanout):
        a = make_ws("WS_a", "U_A")
        b = make_ws("WS_b", "U_B")
        for ws in (a, b):
            node_fanout.register_session(ws)

        await node_fanout.dispatch_envelope({
            "op": "session",
            "session_id": "WS_a",
            "payload": {"type": "session_revoked", "session_id": "WS_a"},
        })

        a.send_json.assert_awaited_once()
        b.send_json.assert_not_called()
        a.close.assert_awaited_once()
        assert "WS_a" not in node_fanout._local_ws_by_session

    async def test_dispatch_subscribe_envelope_adds_local_user_to_room(self, node_fanout):
        ws = make_ws("WS_a", "U_A")
        node_fanout.register_session(ws)

        await node_fanout.dispatch_envelope({
            "op": "subscribe", "user_id": "U_A", "room_id": "CR_new",
        })

        assert ws in node_fanout._room_subs["CR_new"]
        assert "CR_new" in ws.subscribed_rooms

    async def test_dispatch_unsubscribe_envelope_removes_local_user_from_room(self, node_fanout):
        ws = make_ws("WS_a", "U_A")
        node_fanout.register_session(ws)
        node_fanout.register_ws_to_room(ws, "CR_1")

        node_fanout._authorization.lock_room_subscription = MagicMock(
            return_value=authorization_scope(False),
        )

        await node_fanout.dispatch_envelope({
            "op": "unsubscribe", "user_id": "U_A", "room_id": "CR_1",
        })

        assert "CR_1" not in node_fanout._room_subs
        assert "CR_1" not in ws.subscribed_rooms

    async def test_dispatch_unknown_op_drops_silently(self, node_fanout):
        await node_fanout.dispatch_envelope({"op": "future_op", "data": 1})

    async def test_dispatch_envelope_missing_field_drops_silently(self, node_fanout):
        # payload 누락 등 손상된 envelope 도 drop.
        await node_fanout.dispatch_envelope({"op": "room", "room_id": "CR_1"})


def _make_redis_mock_for_publish() -> MagicMock:
    """publish pipeline 호출을 캡처하는 redis mock.

    `pipe.publish` 인자를 자기 list 에 모아 두면 테스트가 envelope payload 까지 검증 가능.
    `pipe.execute` / `redis.publish` / `redis.get` 모두 AsyncMock 으로 await 가능.
    """
    pipe = MagicMock(name="pipe")
    pipe.published: list[tuple[str, str]] = []

    def _publish(channel: str, payload: str):
        pipe.published.append((channel, payload))
        return pipe
    pipe.publish = MagicMock(side_effect=_publish)
    pipe.execute = AsyncMock()

    redis = MagicMock(name="redis")
    redis.pipeline = MagicMock(return_value=pipe)
    redis.publish = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis._pipe = pipe
    return redis


@pytest.fixture
def node_channel_env(monkeypatch):
    """`node_channel` 모드 + redis mock + list_active_nodes mock 셋업.

    반환: `(fanout, redis_mock, set_active_nodes)` 튜플.
    `set_active_nodes(node_ids)` 로 활성 노드 리스트 동적 변경 가능.
    """
    from app.config import setting as setting_module
    monkeypatch.setattr(setting_module.settings, "FANOUT_MODE", "node_channel")

    redis_mock = _make_redis_mock_for_publish()

    async def _get_client():
        return redis_mock
    monkeypatch.setattr(
        "app.domain.chat.service.fanout.get_redis_client", _get_client,
    )

    active: list[str] = []

    async def _list_active_nodes():
        return list(active)
    monkeypatch.setattr(
        "app.domain.chat.service.fanout.list_active_nodes", _list_active_nodes,
    )

    def set_active_nodes(node_ids: list[str]) -> None:
        active.clear()
        active.extend(node_ids)

    from app.domain.chat.service.fanout import FanoutService
    return (
        FanoutService(authorization_service=_allow_all_authorization()),
        redis_mock,
        set_active_nodes,
    )


@pytest.mark.unit
class TestNodeChannelPublish:
    """`node_channel` 모드의 publisher 경로 — envelope 직렬화 + 채널 라우팅 검증."""

    async def test_fan_out_to_room_publishes_to_all_active_nodes(
        self, node_channel_env,
    ):
        fanout, redis_mock, set_active_nodes = node_channel_env
        set_active_nodes(["node-A", "node-B"])

        await fanout.fan_out_to_room("CR_1", {"type": "message.new", "sender_session_id": "S1"})

        assert len(redis_mock._pipe.published) == 2
        channels = [c for c, _ in redis_mock._pipe.published]
        assert channels == ["node:node-A", "node:node-B"]
        envelope = json.loads(redis_mock._pipe.published[0][1])
        assert envelope == {
            "op": "room",
            "room_id": "CR_1",
            "payload": {"type": "message.new", "sender_session_id": "S1"},
            "request_id": "",
            "traceparent": "",
        }
        redis_mock._pipe.execute.assert_awaited_once()

    async def test_fan_out_skips_publish_when_no_active_nodes(
        self, node_channel_env,
    ):
        """startup race 직후 / 전체 shutdown 직후 — 빈 노드 리스트면 publish 자체 skip."""
        fanout, redis_mock, set_active_nodes = node_channel_env
        set_active_nodes([])

        await fanout.fan_out_to_room("CR_1", {"type": "system"})

        redis_mock.pipeline.assert_not_called()

    async def test_fan_out_to_user_publishes_user_envelope(self, node_channel_env):
        fanout, redis_mock, set_active_nodes = node_channel_env
        set_active_nodes(["node-A"])

        await fanout.fan_out_to_user("U_A", {"type": "room_joined", "room_id": "CR_1"})

        envelope = json.loads(redis_mock._pipe.published[0][1])
        assert envelope == {
            "op": "user",
            "user_id": "U_A",
            "payload": {"type": "room_joined", "room_id": "CR_1"},
            "request_id": "",
            "traceparent": "",
        }

    async def test_locked_in_process_subscribe_reuses_caller_authorization(self, fanout):
        ws = make_ws("SID_A", "U_A")
        fanout.register_session(ws)

        await fanout.subscribe_user_to_room(
            "U_A", "CR_new", authorization_locked=True,
        )

        fanout._authorization.lock_room_subscription.assert_not_called()
        assert ws in fanout._room_subs["CR_new"]

    async def test_subscribe_publishes_subscribe_envelope(self, node_channel_env):
        """control-plane subscribe 도 동일 broadcast 경로로 모든 노드에 전파."""
        fanout, redis_mock, set_active_nodes = node_channel_env
        set_active_nodes(["node-A", "node-B"])

        await fanout.subscribe_user_to_room("U_A", "CR_new")

        assert len(redis_mock._pipe.published) == 2
        envelope = json.loads(redis_mock._pipe.published[0][1])
        assert envelope == {
            "op": "subscribe", "user_id": "U_A", "room_id": "CR_new",
            "request_id": "", "traceparent": "",
        }

    async def test_unsubscribe_publishes_unsubscribe_envelope(self, node_channel_env):
        fanout, redis_mock, set_active_nodes = node_channel_env
        set_active_nodes(["node-A"])

        await fanout.unsubscribe_user_from_room("U_A", "CR_1")

        envelope = json.loads(redis_mock._pipe.published[0][1])
        assert envelope == {
            "op": "unsubscribe", "user_id": "U_A", "room_id": "CR_1",
            "request_id": "", "traceparent": "",
        }

    async def test_unsubscribe_cleans_local_state_before_publish_failure(
        self, node_channel_env,
    ):
        fanout, redis_mock, set_active_nodes = node_channel_env
        set_active_nodes(["node-A"])
        websocket = make_ws("WS_A", "U_A")
        fanout.register_session(websocket)
        fanout.register_ws_to_room(websocket, "CR_1")
        fanout._authorization.lock_room_subscription = MagicMock(
            return_value=authorization_scope(False),
        )
        redis_mock._pipe.execute = AsyncMock(side_effect=RuntimeError("redis down"))

        with pytest.raises(RuntimeError, match="redis down"):
            await fanout.unsubscribe_user_from_room("U_A", "CR_1")

        assert "CR_1" not in websocket.subscribed_rooms
        assert "CR_1" not in fanout._room_subs

    async def test_fan_out_to_session_publishes_to_target_node_only(
        self, node_channel_env,
    ):
        """`ws_route:{sid}` 룩업 → 타깃 노드 1곳만 publish (broadcast 낭비 차단)."""
        fanout, redis_mock, set_active_nodes = node_channel_env
        set_active_nodes(["node-A", "node-B", "node-C"])
        redis_mock.get = AsyncMock(return_value="node-B")

        await fanout.fan_out_to_session("SESS_x", {"type": "session_revoked", "session_id": "SESS_x"})

        redis_mock.pipeline.assert_not_called()
        redis_mock.publish.assert_awaited_once()
        channel, payload = redis_mock.publish.await_args.args
        assert channel == "node:node-B"
        envelope = json.loads(payload)
        assert envelope == {
            "op": "session",
            "session_id": "SESS_x",
            "payload": {"type": "session_revoked", "session_id": "SESS_x"},
            "request_id": "",
            "traceparent": "",
        }

    async def test_fan_out_to_session_drops_when_route_missing(
        self, node_channel_env,
    ):
        """세션이 이미 종료돼 `ws_route` 가 없으면 publish 자체 skip — silent drop."""
        fanout, redis_mock, _ = node_channel_env
        redis_mock.get = AsyncMock(return_value=None)

        await fanout.fan_out_to_session("SESS_dead", {"type": "session_revoked", "session_id": "SESS_dead"})

        redis_mock.publish.assert_not_called()


@pytest.mark.unit
class TestReconcileRetry:
    """reconcile 실패(fail-closed unsubscribe) 후 bounded retry 로 구독을 복구한다."""

    @pytest.fixture
    def supervisor(self, monkeypatch):
        """spawn 된 코루틴을 실행하지 않고 수집 — 테스트가 직접 await 해 결정적으로 검증."""
        spawned: list = []
        supervisor = MagicMock()

        def capture(coroutine, **_kwargs):
            spawned.append(coroutine)
            return MagicMock()

        supervisor.spawn.side_effect = capture
        supervisor.spawned = spawned
        monkeypatch.setattr(fanout_module, "background_tasks", supervisor, raising=False)
        return supervisor

    async def test_reconcile_failure_keeps_fail_closed_and_schedules_retry(
        self, fanout, supervisor,
    ):
        ws = make_ws("WS_a", "U_A")
        fanout.register_session(ws)
        fanout.register_ws_to_room(ws, "CR_1")
        fanout._authorization.lock_room_subscription = MagicMock(
            side_effect=lambda _room_id, _user_id: authorization_scope(
                error=RuntimeError("db down"),
            ),
        )

        await fanout._reconcile_room_subscription("U_A", "CR_1")

        assert "CR_1" not in fanout._room_subs
        assert ("U_A", "CR_1") in fanout._pending_reconcile_retries
        supervisor.spawn.assert_called_once()
        supervisor.spawned[0].close()

    async def test_retry_resubscribes_after_db_recovery(
        self, fanout, supervisor, monkeypatch,
    ):
        monkeypatch.setattr(fanout_module, "_RECONCILE_RETRY_DELAYS", (0.0,))
        ws = make_ws("WS_a", "U_A")
        fanout.register_session(ws)
        fanout.register_ws_to_room(ws, "CR_1")
        fanout._authorization.lock_room_subscription = MagicMock(
            side_effect=lambda _room_id, _user_id: authorization_scope(
                error=RuntimeError("db down"),
            ),
        )
        await fanout._reconcile_room_subscription("U_A", "CR_1")
        assert "CR_1" not in fanout._room_subs

        fanout._authorization.lock_room_subscription = MagicMock(
            side_effect=lambda _room_id, _user_id: authorization_scope(True),
        )
        await supervisor.spawned[0]

        assert ws in fanout._room_subs["CR_1"]
        assert ("U_A", "CR_1") not in fanout._pending_reconcile_retries

    async def test_retry_is_not_scheduled_after_exhaustion(
        self, fanout, supervisor, monkeypatch,
    ):
        monkeypatch.setattr(fanout_module, "_RECONCILE_RETRY_DELAYS", (0.0,))
        ws = make_ws("WS_a", "U_A")
        fanout.register_session(ws)
        fanout._authorization.lock_room_subscription = MagicMock(
            side_effect=lambda _room_id, _user_id: authorization_scope(
                error=RuntimeError("db down"),
            ),
        )

        await fanout._reconcile_room_subscription("U_A", "CR_1")
        await supervisor.spawned[0]  # attempt 1 도 실패 → 소진, 추가 예약 없음

        assert supervisor.spawn.call_count == 1
        assert ("U_A", "CR_1") not in fanout._pending_reconcile_retries

    async def test_retry_skips_when_user_left_node(
        self, fanout, supervisor, monkeypatch,
    ):
        monkeypatch.setattr(fanout_module, "_RECONCILE_RETRY_DELAYS", (0.0,))
        ws = make_ws("WS_a", "U_A")
        fanout.register_session(ws)
        fanout.register_ws_to_room(ws, "CR_1")
        fanout._authorization.lock_room_subscription = MagicMock(
            side_effect=lambda _room_id, _user_id: authorization_scope(
                error=RuntimeError("db down"),
            ),
        )
        await fanout._reconcile_room_subscription("U_A", "CR_1")

        recovered = MagicMock(
            side_effect=lambda _room_id, _user_id: authorization_scope(True),
        )
        fanout._authorization.lock_room_subscription = recovered
        fanout.unregister_ws(ws)
        await supervisor.spawned[0]

        recovered.assert_not_called()
        assert "CR_1" not in fanout._room_subs

    async def test_retry_failure_does_not_revoke_resubscribed_state(
        self, fanout, supervisor, monkeypatch,
    ):
        """retry 실패는 새 authorization 이벤트가 아니다 — 그 사이 정당하게 재구독된
        상태를 fail-closed로 철회하지 않는다."""
        monkeypatch.setattr(fanout_module, "_RECONCILE_RETRY_DELAYS", (0.0, 0.0))
        ws = make_ws("WS_a", "U_A")
        fanout.register_session(ws)
        fanout.register_ws_to_room(ws, "CR_1")
        fanout._authorization.lock_room_subscription = MagicMock(
            side_effect=lambda _room_id, _user_id: authorization_scope(
                error=RuntimeError("db down"),
            ),
        )
        await fanout._reconcile_room_subscription("U_A", "CR_1")
        assert "CR_1" not in fanout._room_subs

        # retry 대기 중 invite(authorization_locked) 경로로 정당하게 재구독
        fanout._local_subscribe_user_to_room("U_A", "CR_1")
        await supervisor.spawned[0]  # retry attempt 1 — 여전히 DB down

        assert ws in fanout._room_subs["CR_1"]
        supervisor.spawned[1].close()  # attempt 2 예약분 정리
