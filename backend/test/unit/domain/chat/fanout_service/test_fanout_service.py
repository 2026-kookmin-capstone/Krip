"""FanoutService 단위 테스트 — in-process dict fan-out 의 핵심 동작 검증."""
import pytest

from test.unit.domain.chat.fanout_service.conftest import make_ws


# ──────────────────────────────────────────────────────────────────
# 등록 / 해제
# ──────────────────────────────────────────────────────────────────

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
        assert "CR_1" in ws.subscribed_rooms  # 역매핑


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

        fanout.unregister_ws(ws_a)

        # WS_a 는 완전히 제거, WS_b 는 유지
        assert "WS_a" not in fanout._local_ws_by_session
        assert "WS_b" in fanout._local_ws_by_session
        assert "U_A" not in fanout._user_subs  # 빈 set → key 제거
        assert ws_b in fanout._user_subs["U_B"]
        assert ws_a not in fanout._room_subs["CR_1"]
        assert ws_b in fanout._room_subs["CR_1"]
        assert "CR_2" not in fanout._room_subs  # 혼자 있던 방은 key 까지 제거

    def test_unregister_tolerates_missing_attributes(self, fanout):
        """속성이 없는 WS 라도 예외 없이 지나가야 한다 (방어적)."""
        ws = make_ws("WS_1", "U_A")
        # subscribed_rooms 를 의도적으로 지워서 방어 확인
        del ws.subscribed_rooms
        fanout.register_session(ws)
        # 예외 없이 통과
        fanout.unregister_ws(ws)

        assert "WS_1" not in fanout._local_ws_by_session


# ──────────────────────────────────────────────────────────────────
# fan_out_to_room
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestFanOutToRoom:
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

        phone.send_json.assert_not_called()       # 발신자 skip
        pc.send_json.assert_awaited_once()         # 같은 유저 다른 세션
        bob.send_json.assert_awaited_once()        # 다른 유저

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


# ──────────────────────────────────────────────────────────────────
# fan_out_to_user / fan_out_to_session
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestFanOutToUser:
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

    async def test_missing_session_silent(self, fanout):
        """이미 close 된 세션은 dict 에서 pop 된 상태 — 조용히 무시."""
        await fanout.fan_out_to_session("WS_ghost", {"type": "session_revoked", "session_id": "?"})


# ──────────────────────────────────────────────────────────────────
# 에러 허용 / FANOUT_MODE 가드
# ──────────────────────────────────────────────────────────────────

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

        # 예외 새지 않고 통과
        await fanout.fan_out_to_room("CR_1", {"type": "system"})
        ok.send_json.assert_awaited_once()


@pytest.mark.unit
class TestFanoutModeGuard:
    def test_node_channel_mode_raises(self, monkeypatch):
        """Phase 4 전용 모드로 잘못 기동하면 생성자에서 NotImplementedError."""
        from app.config import setting as setting_module
        monkeypatch.setattr(setting_module.settings, "FANOUT_MODE", "node_channel")

        from app.domain.chat.service.fanout import FanoutService
        with pytest.raises(NotImplementedError, match="Phase 4"):
            FanoutService()
