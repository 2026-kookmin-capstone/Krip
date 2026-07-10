"""MessageService 단위 테스트 — 송신 11단계 핫패스 / 재시도 / dedupe / unread."""
from unittest.mock import AsyncMock

import pytest
from pymongo.errors import DuplicateKeyError

from app.core.chat.redis_key import (
    DIRTY_CHAT_ROOM_KEY,
    RATE_LIMIT_THRESHOLD,
    dedupe_key,
)
from app.domain.chat.model.chat_message import MessageType
from app.domain.chat.service.exception import UpstreamError


# ──────────────────────────────────────────────────────────────────
# 핫패스 성공 경로
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestHappyPath:
    async def test_returns_ack_with_server_seq(self, service, lua_mock):
        lua_mock.incr_fast.return_value = 42

        ack = await service.send_message(
            sender_user_id="U_A",
            sender_session_id="WS_A",
            room_id="CR_1",
            client_msg_id="cm-1",
            msg_type=MessageType.TEXT,
            content="안녕",
        )

        assert ack.client_msg_id == "cm-1"
        assert ack.server_seq == 42
        assert ack.message_id.startswith("MSG_")

    async def test_fans_out_to_room_with_sender_session_id(
        self, service, fanout_mock, lua_mock,
    ):
        lua_mock.incr_fast.return_value = 10

        await service.send_message(
            sender_user_id="U_A",
            sender_session_id="WS_A",
            room_id="CR_1",
            client_msg_id="cm-1",
            msg_type=MessageType.TEXT,
            content="hi",
        )

        fanout_mock.fan_out_to_room.assert_awaited_once()
        args, _ = fanout_mock.fan_out_to_room.call_args
        assert args[0] == "CR_1"
        payload = args[1]
        assert payload["type"] == "message.new"
        assert payload["sender_session_id"] == "WS_A"
        assert payload["message"]["server_seq"] == 10
        assert payload["message"]["content"] == "hi"

    async def test_updates_rdb_last_message_and_inserts_mongo(
        self, service, chat_room_repo_mock, message_repo_mock, lua_mock,
    ):
        lua_mock.incr_fast.return_value = 7

        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
        )

        # Mongo insert 1회
        message_repo_mock.insert.assert_awaited_once()
        doc = message_repo_mock.insert.call_args.args[0]
        assert doc["server_seq"] == 7
        assert doc["chat_room_id"] == "CR_1"
        assert doc["type"] == "text"

        # RDB update_last_message_if_greater 1회 (seq 가드로 동시 송신 regress 방지)
        chat_room_repo_mock.update_last_message_if_greater.assert_awaited_once()
        kwargs = chat_room_repo_mock.update_last_message_if_greater.call_args.kwargs
        assert kwargs["chat_room_id"] == "CR_1"
        assert kwargs["server_seq"] == 7


# ──────────────────────────────────────────────────────────────────
# 멤버십 검증 (§5.1-2)
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestMembershipCheck:
    async def test_cache_hit_skips_full_member_load(
        self, service, redis_mock, chat_member_repo_mock,
    ):
        redis_mock.sismember = AsyncMock(return_value=True)

        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
        )

        chat_member_repo_mock.is_active_member_for_share.assert_awaited_once_with("CR_1", "U_A")
        chat_member_repo_mock.find_active_member_ids.assert_not_called()

    async def test_cache_hit_rejects_member_who_left_rdb(
        self, service, redis_mock, chat_member_repo_mock, message_repo_mock,
    ):
        redis_mock.sismember = AsyncMock(return_value=True)
        chat_member_repo_mock.is_active_member_for_share.return_value = False

        with pytest.raises(PermissionError, match="멤버가 아닙니다"):
            await service.send_message(
                sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
                client_msg_id="cm-stale", msg_type=MessageType.TEXT, content="x",
            )

        message_repo_mock.insert.assert_not_awaited()

    async def test_cache_hit_refreshes_ttl(self, service, redis_mock):
        """sismember 히트 시 room:members TTL 을 슬라이딩 — 후속 smembers 만료 race 방지."""
        redis_mock.sismember = AsyncMock(return_value=True)

        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-ttl", msg_type=MessageType.TEXT, content="x",
        )

        redis_mock.expire.assert_awaited()
        from app.core.chat.redis_key import ROOM_MEMBERS_TTL, room_members_key
        assert redis_mock.expire.call_args.args == (room_members_key("CR_1"), ROOM_MEMBERS_TTL)

    async def test_cache_miss_loads_all_members_and_sadd(
        self, service, redis_mock, chat_member_repo_mock, lua_mock,
    ):
        redis_mock.sismember = AsyncMock(return_value=False)
        chat_member_repo_mock.find_active_member_ids.return_value = ["U_A", "U_B"]

        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
        )

        chat_member_repo_mock.find_active_member_ids.assert_awaited_once_with("CR_1")
        # 멤버 populate 는 gen 가드 Lua(populate_members)로 반영 — gen0 캡처 후 멤버 목록 전달.
        lua_mock.populate_members.assert_awaited_once()
        args = lua_mock.populate_members.call_args.kwargs["args"]
        assert set(args[2:]) == {"U_A", "U_B"}, "멤버 목록이 Lua ARGV 로 전달되지 않음"

    async def test_not_a_member_raises_permission(
        self, service, redis_mock, chat_member_repo_mock,
    ):
        redis_mock.sismember = AsyncMock(return_value=False)
        chat_member_repo_mock.find_active_member_ids.return_value = ["U_B", "U_C"]  # U_A 없음

        with pytest.raises(PermissionError, match="멤버가 아닙니다"):
            await service.send_message(
                sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
                client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
            )


# ──────────────────────────────────────────────────────────────────
# Rate limit
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRateLimit:
    async def test_exceeding_threshold_raises(self, service, lua_mock):
        lua_mock.incr_with_ttl.return_value = RATE_LIMIT_THRESHOLD + 1

        with pytest.raises(ValueError, match="속도 제한"):
            await service.send_message(
                sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
                client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
            )


# ──────────────────────────────────────────────────────────────────
# Dedupe
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestDedupe:
    async def test_duplicate_in_flight_raises_retryable(
        self, service, redis_dedupe_mock,
    ):
        """dedupe hit + 값이 아직 placeholder → 최초 전송 in-flight → 재시도 유도 에러."""
        redis_dedupe_mock.set = AsyncMock(return_value=False)  # SET NX 실패 = 이미 있음
        redis_dedupe_mock.get = AsyncMock(return_value="1")    # placeholder (ACK 미기록)

        with pytest.raises(ValueError, match="처리 중"):
            await service.send_message(
                sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
                client_msg_id="cm-dup", msg_type=MessageType.TEXT, content="x",
            )

    async def test_duplicate_replays_recorded_ack(
        self, service, redis_dedupe_mock,
    ):
        """dedupe hit + 값에 ACK 기록됨 → 원본 ACK 를 replay (ACK 유실 클라 구제, 에러 아님)."""
        import json
        redis_dedupe_mock.set = AsyncMock(return_value=False)
        redis_dedupe_mock.get = AsyncMock(return_value=json.dumps({
            "room_id": "CR_1",
            "message_id": "MSG_original",
            "server_seq": 42,
            "created_at": "2026-07-09T00:00:00+00:00",
        }))

        ack = await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-dup", msg_type=MessageType.TEXT, content="x",
        )

        assert ack.message_id == "MSG_original"
        assert ack.server_seq == 42
        assert ack.client_msg_id == "cm-dup"

    async def test_left_member_can_replay_recorded_ack_for_same_room(
        self, service, redis_dedupe_mock, chat_member_repo_mock,
        chat_room_repo_mock, message_repo_mock, lua_mock,
    ):
        import json
        chat_member_repo_mock.is_active_member_for_share.return_value = False
        redis_dedupe_mock.get = AsyncMock(return_value=json.dumps({
            "room_id": "CR_1",
            "message_id": "MSG_original",
            "server_seq": 42,
            "created_at": "2026-07-09T00:00:00+00:00",
        }))

        ack = await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-dup", msg_type=MessageType.TEXT, content="x",
        )

        assert ack.message_id == "MSG_original"
        chat_member_repo_mock.is_active_member_for_share.assert_not_awaited()
        chat_room_repo_mock.find_by_id.assert_not_awaited()
        message_repo_mock.insert.assert_not_awaited()
        lua_mock.incr_with_ttl.assert_not_awaited()
        redis_dedupe_mock.set.assert_not_awaited()

    async def test_left_member_cannot_replay_ack_from_another_room(
        self, service, redis_dedupe_mock, chat_member_repo_mock,
    ):
        import json
        chat_member_repo_mock.is_active_member_for_share.return_value = False
        redis_dedupe_mock.get = AsyncMock(return_value=json.dumps({
            "room_id": "CR_OTHER",
            "message_id": "MSG_other",
            "server_seq": 7,
            "created_at": "2026-07-09T00:00:00+00:00",
        }))

        with pytest.raises(PermissionError, match="멤버가 아닙니다"):
            await service.send_message(
                sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
                client_msg_id="cm-dup", msg_type=MessageType.TEXT, content="x",
            )

        chat_member_repo_mock.is_active_member_for_share.assert_awaited_once_with("CR_1", "U_A")

    async def test_legacy_ack_requires_active_membership(
        self, service, redis_dedupe_mock, chat_member_repo_mock,
    ):
        import json
        chat_member_repo_mock.is_active_member_for_share.return_value = False
        redis_dedupe_mock.get = AsyncMock(return_value=json.dumps({
            "message_id": "MSG_legacy",
            "server_seq": 3,
            "created_at": "2026-07-09T00:00:00+00:00",
        }))

        with pytest.raises(PermissionError, match="멤버가 아닙니다"):
            await service.send_message(
                sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
                client_msg_id="cm-legacy", msg_type=MessageType.TEXT, content="x",
            )

    async def test_active_member_can_replay_legacy_ack(
        self, service, redis_dedupe_mock,
    ):
        import json
        redis_dedupe_mock.set = AsyncMock(return_value=False)
        redis_dedupe_mock.get = AsyncMock(return_value=json.dumps({
            "message_id": "MSG_legacy",
            "server_seq": 3,
            "created_at": "2026-07-09T00:00:00+00:00",
        }))

        ack = await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-legacy", msg_type=MessageType.TEXT, content="x",
        )

        assert ack.message_id == "MSG_legacy"

    async def test_dedupe_key_uses_user_scope(
        self, service, redis_dedupe_mock,
    ):
        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
        )
        # dedupe:{user_id}:{client_msg_id} 형태로 SET
        args, _ = redis_dedupe_mock.set.call_args
        assert args[0] == dedupe_key("U_A", "cm-1")

    async def test_recorded_ack_is_scoped_to_room(self, service, redis_dedupe_mock):
        import json
        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
        )

        ack_payload = json.loads(redis_dedupe_mock.set.await_args.args[1])
        assert ack_payload["room_id"] == "CR_1"


# ──────────────────────────────────────────────────────────────────
# seq 채번
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestSeqAllocation:
    async def test_hot_path_uses_incr_fast(self, service, lua_mock):
        lua_mock.incr_fast.return_value = 100

        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
        )

        lua_mock.incr_fast.assert_awaited_once()
        lua_mock.recover_and_incr.assert_not_called()

    async def test_recover_path_when_incr_fast_returns_minus_one(
        self, service, lua_mock, message_repo_mock,
    ):
        """incr_fast == -1 → Mongo max 조회 → recover_and_incr 호출."""
        lua_mock.incr_fast.return_value = -1
        lua_mock.recover_and_incr.return_value = 1001
        message_repo_mock.get_max_server_seq.return_value = 500

        ack = await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
        )

        message_repo_mock.get_max_server_seq.assert_awaited_once_with("CR_1")
        lua_mock.recover_and_incr.assert_awaited_once()
        assert ack.server_seq == 1001

    async def test_recover_path_first_message_uses_base_zero(
        self, service, lua_mock, message_repo_mock,
    ):
        """Mongo max=0 (신규 방) → base=0 → seq=1 로 출발."""
        lua_mock.incr_fast.return_value = -1
        lua_mock.recover_and_incr.return_value = 1
        message_repo_mock.get_max_server_seq.return_value = 0

        ack = await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
        )

        args = lua_mock.recover_and_incr.call_args.kwargs.get("args") \
            or lua_mock.recover_and_incr.call_args.args[1:]
        # base 가 0 (mongo_max == 0 분기)
        assert 0 in list(args)
        assert ack.server_seq == 1


# ──────────────────────────────────────────────────────────────────
# DuplicateKey 재시도
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestDuplicateKeyRetry:
    async def test_first_retry_uses_force_jump(
        self, service, message_repo_mock, lua_mock,
    ):
        # 첫 insert 실패 → 두 번째 성공
        message_repo_mock.insert.side_effect = [
            DuplicateKeyError("dup"),
            None,  # 재시도 성공
        ]
        lua_mock.incr_fast.return_value = 50
        lua_mock.force_jump.return_value = 1050

        ack = await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
        )

        assert lua_mock.force_jump.await_count == 1
        assert message_repo_mock.insert.await_count == 2
        assert ack.server_seq == 1050

    async def test_three_failures_raise_upstream_and_clear_dedupe(
        self, service, message_repo_mock, redis_dedupe_mock, lua_mock,
    ):
        """3회 연속 DuplicateKey → UpstreamError + dedupe DEL."""
        message_repo_mock.insert.side_effect = DuplicateKeyError("dup")
        lua_mock.force_jump.return_value = 1000

        with pytest.raises(UpstreamError):
            await service.send_message(
                sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
                client_msg_id="cm-fail", msg_type=MessageType.TEXT, content="x",
            )

        # dedupe 해제되어 클라 재시도 허용
        redis_dedupe_mock.delete.assert_awaited()
        args, _ = redis_dedupe_mock.delete.call_args
        assert args[0] == dedupe_key("U_A", "cm-fail")

        # force_jump 는 3회 (1회차 실패 후 + 2회차 실패 후 + 3회차 실패 후)
        assert lua_mock.force_jump.await_count == 3


# ──────────────────────────────────────────────────────────────────
# Dedupe 해제 경계 — Mongo 저장 성공 전 어떤 실패든 dedupe 풀어 클라 재시도 허용
#
# regression: 이전 구현은 (7) Mongo insert 단계에서 `except DuplicateKeyError` 만
# 잡아 ConnectionFailure 등 다른 Mongo 예외가 나면 dedupe 가 영구 잔존해
# 같은 client_msg_id 가 DEDUPE_TTL(10분) 동안 차단되던 버그가 있었음.
# (6)+(7) 단계를 단일 try/except 로 묶어 모든 비-DuplicateKey 예외도 커버.
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestDedupeReleaseOnFailure:
    async def test_mongo_connection_failure_clears_dedupe(
        self, service, message_repo_mock, redis_dedupe_mock,
    ):
        """Mongo ConnectionFailure → 즉시 propagate + dedupe DEL.

        DuplicateKey 가 아닌 Mongo 예외 (네트워크 / 타임아웃) 시 dedupe 가 정리되지
        않으면 같은 client_msg_id 로 재시도가 영구 차단된다.
        """
        from pymongo.errors import ConnectionFailure
        message_repo_mock.insert.side_effect = ConnectionFailure("simulated")

        with pytest.raises(ConnectionFailure):
            await service.send_message(
                sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
                client_msg_id="cm-conn", msg_type=MessageType.TEXT, content="x",
            )

        redis_dedupe_mock.delete.assert_awaited()
        args, _ = redis_dedupe_mock.delete.call_args
        assert args[0] == dedupe_key("U_A", "cm-conn")

    async def test_seq_allocation_failure_clears_dedupe(
        self, service, lua_mock, redis_dedupe_mock,
    ):
        """seq 채번 (incr_fast Lua) 실패 시에도 dedupe 정리 — 기존 동작 회귀 보호."""
        lua_mock.incr_fast.side_effect = RuntimeError("redis lua error")

        with pytest.raises(RuntimeError):
            await service.send_message(
                sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
                client_msg_id="cm-seq", msg_type=MessageType.TEXT, content="x",
            )

        redis_dedupe_mock.delete.assert_awaited()
        args, _ = redis_dedupe_mock.delete.call_args
        assert args[0] == dedupe_key("U_A", "cm-seq")

    async def test_happy_path_keeps_dedupe(
        self, service, redis_dedupe_mock,
    ):
        """정상 송신 시 dedupe 는 유지 — 같은 client_msg_id 재전송을 차단해야 함.

        regression: dedupe 해제 try/except 가 너무 넓어져 성공 경로까지 풀어버리면
        dedupe 자체의 목적이 무너진다. 경계가 'Mongo insert 성공' 직전까지여야 함.
        """
        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-ok", msg_type=MessageType.TEXT, content="x",
        )
        redis_dedupe_mock.delete.assert_not_called()


# ──────────────────────────────────────────────────────────────────
# Persist 이후 전파(unread/fanout) 는 best-effort — 저장된 메시지는 항상 ACK 반환
#
# regression: 이전엔 fanout/unread 예외가 그대로 전파돼 (a) 저장된 메시지에 대해
# 클라가 ACK 대신 에러 → dedupe 잔존으로 재전송도 거절 → 영구 실패로 보이고,
# (b) @transactional rollback 으로 last_message 갱신까지 유실됐다.
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPostPersistPropagationBestEffort:
    async def test_fanout_failure_still_returns_ack_and_keeps_dedupe(
        self, service, fanout_mock, redis_dedupe_mock, lua_mock,
    ):
        """fanout 실패 → 예외 미전파, ACK 정상 반환, dedupe 유지."""
        lua_mock.incr_fast.return_value = 7
        fanout_mock.fan_out_to_room.side_effect = RuntimeError("redis pub/sub down")

        ack = await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-fanout-fail", msg_type=MessageType.TEXT, content="x",
        )

        assert ack.server_seq == 7
        assert ack.client_msg_id == "cm-fanout-fail"
        # 저장 성공 후 실패라 dedupe 를 풀면 안 됨 (재전송 시 중복 저장 위험)
        redis_dedupe_mock.delete.assert_not_called()

    async def test_unread_bump_failure_still_returns_ack(
        self, service, redis_dedupe_mock, lua_mock,
    ):
        """unread 증가 실패 → 예외 미전파, ACK 정상 반환."""
        lua_mock.incr_fast.return_value = 8
        service._bump_unread = AsyncMock(side_effect=RuntimeError("hincrby failed"))

        ack = await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-unread-fail", msg_type=MessageType.TEXT, content="x",
        )

        assert ack.server_seq == 8
        redis_dedupe_mock.delete.assert_not_called()


# ──────────────────────────────────────────────────────────────────
# RDB UPDATE 실패 → dirty 큐
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRdbUpdateFailureDegrade:
    async def test_update_last_message_failure_adds_to_dirty_queue(
        self, service, chat_room_repo_mock, redis_mock, mock_session,
    ):
        # SAVEPOINT 내 last_message UPDATE 실패를 재현 → dirty 큐로 위임돼야 함.
        chat_room_repo_mock.update_last_message_if_greater = AsyncMock(
            side_effect=RuntimeError("RDB connection reset"),
        )

        # 송신은 계속 진행되어 ACK 성공해야 함
        ack = await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
        )

        # dirty:chat_room 에 방 ID 적재 확인
        redis_mock.sadd.assert_awaited()
        calls = redis_mock.sadd.await_args_list
        dirty_calls = [c for c in calls if c.args[0] == DIRTY_CHAT_ROOM_KEY]
        assert dirty_calls
        assert dirty_calls[0].args[1] == "CR_1"
        assert ack.server_seq  # 정상 발급


# ──────────────────────────────────────────────────────────────────
# Unread pipeline
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestUnread:
    async def test_bumps_unread_for_other_members_only(self, service, redis_mock):
        redis_mock.smembers = AsyncMock(return_value={"U_A", "U_B", "U_C"})

        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
        )

        # unread pipeline 에서 hincrby 는 발신자 제외 2회 (U_B, U_C)
        unread_pipes = [p for p in redis_mock._pipes if p.hincrby.called]
        assert unread_pipes, "unread pipeline 이 호출되지 않음"
        p = unread_pipes[-1]
        incrby_targets = {c.args[0] for c in p.hincrby.call_args_list}
        # unread:{user_id} 키에 대해
        assert len(incrby_targets) == 2
        senders_in_pipe = {c.args[0].split(":")[1] for c in p.hincrby.call_args_list}
        assert senders_in_pipe == {"U_B", "U_C"}

    async def test_system_message_skips_unread(self, service, redis_mock):
        redis_mock.smembers = AsyncMock(return_value={"U_A", "U_B"})

        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.SYSTEM, content="joined",
        )

        # 시스템 메시지 → unread 증가 안 함
        unread_pipes = [p for p in redis_mock._pipes if p.hincrby.called]
        assert not unread_pipes, "시스템 메시지인데 unread HINCRBY 가 호출됨"


# ──────────────────────────────────────────────────────────────────
# send_system_message (PHASE_2 #2) — dedupe/rate_limit/unread skip,
# content 는 dict, sender_id 는 None, fan-out 은 message.new 재사용
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestSendSystemMessage:
    async def test_records_system_doc_with_none_sender_and_dict_content(
        self, service, message_repo_mock,
    ):
        await service.send_system_message(
            room_id="CR_1", action="created", actor_id="U_A",
        )

        message_repo_mock.insert.assert_awaited_once()
        doc = message_repo_mock.insert.call_args.args[0]
        assert doc["sender_id"] is None
        assert doc["type"] == "system"
        assert doc["content"] == {"action": "created", "actor_id": "U_A"}

    async def test_includes_target_ids_when_provided(
        self, service, message_repo_mock,
    ):
        await service.send_system_message(
            room_id="CR_1", action="join", actor_id="U_A", target_ids=["U_B", "U_C"],
        )
        doc = message_repo_mock.insert.call_args.args[0]
        assert doc["content"] == {
            "action": "join", "actor_id": "U_A", "target_ids": ["U_B", "U_C"],
        }

    async def test_skips_dedupe_and_rate_limit(
        self, service, redis_dedupe_mock, lua_mock,
    ):
        await service.send_system_message(
            room_id="CR_1", action="leave", actor_id="U_A",
        )
        redis_dedupe_mock.set.assert_not_called()
        lua_mock.incr_with_ttl.assert_not_called()

    async def test_skips_unread_pipeline(
        self, service, redis_mock,
    ):
        await service.send_system_message(
            room_id="CR_1", action="kick", actor_id="U_A", target_ids=["U_B"],
        )
        unread_pipes = [p for p in redis_mock._pipes if p.hincrby.called]
        assert not unread_pipes, "시스템 메시지인데 unread HINCRBY 가 호출됨"

    async def test_fans_out_to_room_as_message_new(
        self, service, fanout_mock,
    ):
        await service.send_system_message(
            room_id="CR_1", action="created", actor_id="U_A",
            actor_session_id="WS_A",
        )
        fanout_mock.fan_out_to_room.assert_awaited_once()
        payload = fanout_mock.fan_out_to_room.call_args.args[1]
        assert payload["type"] == "message.new"
        assert payload["sender_session_id"] == "WS_A"
        assert payload["message"]["type"] == "system"
        assert payload["message"]["sender_id"] is None
        assert payload["message"]["content"]["action"] == "created"

    async def test_updates_last_message_with_seq_guard(
        self, service, chat_room_repo_mock,
    ):
        """시스템 메시지도 방 리스트의 last_message 에 반영 — "OO 님이 방을 만들었습니다" 가
        preview 로 뜨도록. 단, if_greater 가드로 유저 메시지와 엇갈려도 regress 하지 않는다."""
        await service.send_system_message(
            room_id="CR_1", action="created", actor_id="U_A",
        )
        # 가드 없는 update_last_message 가 아니라 if_greater 가드 경로를 쓴다 (regress 차단).
        chat_room_repo_mock.update_last_message.assert_not_awaited()
        chat_room_repo_mock.update_last_message_if_greater.assert_awaited_once()
        kwargs = chat_room_repo_mock.update_last_message_if_greater.call_args.kwargs
        assert kwargs["chat_room_id"] == "CR_1"


# ──────────────────────────────────────────────────────────────────
# edit_message (PHASE_2 #5) — 본인 메시지 5분 이내 편집
# ──────────────────────────────────────────────────────────────────

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.domain.chat.model.chat_room import ChatRoomType


def _mk_text_doc(
    *,
    message_id: str = "MSG_1",
    chat_room_id: str = "CR_1",
    sender_id: str = "U_A",
    created_at: datetime | None = None,
    deleted_at: datetime | None = None,
    msg_type: str = "text",
) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "_id": message_id,
        "chat_room_id": chat_room_id,
        "server_seq": 1,
        "sender_id": sender_id,
        "type": msg_type,
        "content": "hi",
        "created_at": created_at if created_at is not None else now,
        "edited_at": None,
        "deleted_at": deleted_at,
    }


@pytest.mark.unit
class TestEditMessage:
    async def test_raises_when_message_missing(self, service, message_repo_mock):
        message_repo_mock.find_by_id.return_value = None
        with pytest.raises(ValueError, match="존재하지 않는"):
            await service.edit_message(
                message_id="MSG_X", editor_user_id="U_A", editor_session_id="WS_A",
                new_content="new",
            )

    async def test_raises_on_deleted_message(self, service, message_repo_mock):
        message_repo_mock.find_by_id.return_value = _mk_text_doc(
            deleted_at=datetime.now(timezone.utc),
        )
        with pytest.raises(ValueError, match="삭제된 메시지"):
            await service.edit_message(
                message_id="MSG_1", editor_user_id="U_A", editor_session_id="WS_A",
                new_content="new",
            )

    async def test_raises_on_system_message(self, service, message_repo_mock):
        message_repo_mock.find_by_id.return_value = _mk_text_doc(
            msg_type="system", sender_id=None,
        )
        with pytest.raises(PermissionError, match="시스템"):
            await service.edit_message(
                message_id="MSG_1", editor_user_id="U_A", editor_session_id="WS_A",
                new_content="new",
            )

    async def test_raises_when_editor_not_owner(self, service, message_repo_mock):
        message_repo_mock.find_by_id.return_value = _mk_text_doc(sender_id="U_A")
        with pytest.raises(PermissionError, match="본인 메시지"):
            await service.edit_message(
                message_id="MSG_1", editor_user_id="U_B", editor_session_id="WS_B",
                new_content="new",
            )

    async def test_raises_when_editor_not_active_member(
        self, service, message_repo_mock, chat_member_repo_mock,
    ):
        message_repo_mock.find_by_id.return_value = _mk_text_doc(sender_id="U_A")
        chat_member_repo_mock.is_active_member.return_value = False
        with pytest.raises(PermissionError, match="활성 멤버"):
            await service.edit_message(
                message_id="MSG_1", editor_user_id="U_A", editor_session_id="WS_A",
                new_content="new",
            )

    async def test_allowed_at_4m59s(self, service, message_repo_mock):
        """4분 59초 경과 — 5분 제한 직전이므로 성공."""
        created = datetime.now(timezone.utc) - timedelta(minutes=4, seconds=59)
        message_repo_mock.find_by_id.return_value = _mk_text_doc(created_at=created)
        result = await service.edit_message(
            message_id="MSG_1", editor_user_id="U_A", editor_session_id="WS_A",
            new_content="new",
        )
        assert result["message_id"] == "MSG_1"
        assert result["content"] == "new"
        message_repo_mock.update_content.assert_awaited_once()

    async def test_rejected_at_5m01s(self, service, message_repo_mock):
        """5분 1초 경과 — 제한 초과."""
        created = datetime.now(timezone.utc) - timedelta(minutes=5, seconds=1)
        message_repo_mock.find_by_id.return_value = _mk_text_doc(created_at=created)
        with pytest.raises(ValueError, match="5분"):
            await service.edit_message(
                message_id="MSG_1", editor_user_id="U_A", editor_session_id="WS_A",
                new_content="new",
            )
        message_repo_mock.update_content.assert_not_called()

    async def test_successful_edit_fans_out_updated_event(
        self, service, message_repo_mock, fanout_mock,
    ):
        message_repo_mock.find_by_id.return_value = _mk_text_doc()
        await service.edit_message(
            message_id="MSG_1", editor_user_id="U_A", editor_session_id="WS_A",
            new_content="updated body",
        )
        fanout_mock.fan_out_to_room.assert_awaited_once()
        args = fanout_mock.fan_out_to_room.call_args.args
        assert args[0] == "CR_1"
        payload = args[1]
        assert payload["type"] == "message.updated"
        assert payload["sender_session_id"] == "WS_A"
        assert payload["message_id"] == "MSG_1"
        assert payload["content"] == "updated body"
        assert "edited_at" in payload


# ──────────────────────────────────────────────────────────────────
# delete_message (PHASE_2 #5) — 본인 OR 그룹방 creator soft delete
# ──────────────────────────────────────────────────────────────────

def _mk_room(
    chat_room_id: str = "CR_1",
    *,
    type_: ChatRoomType = ChatRoomType.GROUP,
    creator_id: str | None = "U_creator",
) -> SimpleNamespace:
    return SimpleNamespace(
        chat_room_id=chat_room_id,
        type=type_,
        creator_id=creator_id,
    )


@pytest.mark.unit
class TestDeleteMessage:
    async def test_raises_when_message_missing(self, service, message_repo_mock):
        message_repo_mock.find_by_id.return_value = None
        with pytest.raises(ValueError, match="존재하지 않는"):
            await service.delete_message(
                message_id="MSG_X", deleter_user_id="U_A", deleter_session_id="WS_A",
            )

    async def test_raises_on_already_deleted(self, service, message_repo_mock):
        message_repo_mock.find_by_id.return_value = _mk_text_doc(
            deleted_at=datetime.now(timezone.utc),
        )
        with pytest.raises(ValueError, match="이미 삭제"):
            await service.delete_message(
                message_id="MSG_1", deleter_user_id="U_A", deleter_session_id="WS_A",
            )

    async def test_raises_on_system_message(self, service, message_repo_mock):
        message_repo_mock.find_by_id.return_value = _mk_text_doc(
            msg_type="system", sender_id=None,
        )
        with pytest.raises(PermissionError, match="시스템"):
            await service.delete_message(
                message_id="MSG_1", deleter_user_id="U_A", deleter_session_id="WS_A",
            )

    async def test_raises_when_deleter_not_active_member(
        self, service, message_repo_mock, chat_member_repo_mock,
    ):
        message_repo_mock.find_by_id.return_value = _mk_text_doc(sender_id="U_A")
        chat_member_repo_mock.is_active_member.return_value = False
        with pytest.raises(PermissionError, match="활성 멤버"):
            await service.delete_message(
                message_id="MSG_1", deleter_user_id="U_A", deleter_session_id="WS_A",
            )

    async def test_own_message_soft_deleted_and_fanned_out(
        self, service, message_repo_mock, fanout_mock,
    ):
        message_repo_mock.find_by_id.return_value = _mk_text_doc(sender_id="U_A")
        await service.delete_message(
            message_id="MSG_1", deleter_user_id="U_A", deleter_session_id="WS_A",
        )
        message_repo_mock.soft_delete.assert_awaited_once()
        fanout_mock.fan_out_to_room.assert_awaited_once()
        payload = fanout_mock.fan_out_to_room.call_args.args[1]
        assert payload["type"] == "message.deleted"
        assert payload["sender_session_id"] == "WS_A"
        assert payload["message_id"] == "MSG_1"

    async def test_group_creator_can_delete_others(
        self, service, message_repo_mock, chat_room_repo_mock,
    ):
        # 다른 유저 메시지지만 나는 group creator
        message_repo_mock.find_by_id.return_value = _mk_text_doc(sender_id="U_B")
        chat_room_repo_mock.find_by_id.return_value = _mk_room(
            type_=ChatRoomType.GROUP, creator_id="U_A",
        )
        await service.delete_message(
            message_id="MSG_1", deleter_user_id="U_A", deleter_session_id="WS_A",
        )
        message_repo_mock.soft_delete.assert_awaited_once()

    async def test_non_creator_cannot_delete_others(
        self, service, message_repo_mock, chat_room_repo_mock,
    ):
        message_repo_mock.find_by_id.return_value = _mk_text_doc(sender_id="U_B")
        chat_room_repo_mock.find_by_id.return_value = _mk_room(
            type_=ChatRoomType.GROUP, creator_id="U_other",
        )
        with pytest.raises(PermissionError, match="본인 메시지 또는 그룹 방장"):
            await service.delete_message(
                message_id="MSG_1", deleter_user_id="U_A", deleter_session_id="WS_A",
            )
        message_repo_mock.soft_delete.assert_not_called()

    async def test_direct_room_creator_cannot_delete_others(
        self, service, message_repo_mock, chat_room_repo_mock,
    ):
        """direct 방은 'creator' 라도 상대 메시지 삭제 권한 없음 — 그룹 방에만 적용."""
        message_repo_mock.find_by_id.return_value = _mk_text_doc(sender_id="U_B")
        chat_room_repo_mock.find_by_id.return_value = _mk_room(
            type_=ChatRoomType.DIRECT, creator_id="U_A",
        )
        with pytest.raises(PermissionError):
            await service.delete_message(
                message_id="MSG_1", deleter_user_id="U_A", deleter_session_id="WS_A",
            )


# ──────────────────────────────────────────────────────────────────
# (4) 차단 체크 — DIRECT 방만 room:blocks SISMEMBER 검사 (PHASE_2 #6)
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestDirectBlockCheck:
    @pytest.fixture
    def block_repo_mock(self, monkeypatch):
        mock = AsyncMock()
        mock.find_blocks_between.return_value = []
        monkeypatch.setattr(
            "app.domain.chat.service.message.UserBlockRepository",
            lambda session: mock,
        )
        return mock

    @pytest.fixture
    def direct_room_mock(self, chat_room_repo_mock):
        """chat_room_repo.find_by_id 가 DIRECT 방을 반환하도록 override."""
        room = SimpleNamespace(
            chat_room_id="CR_1",
            type=ChatRoomType.DIRECT,
            creator_id="U_A",
            direct_user_a_id="U_A",
            direct_user_b_id="U_B",
        )
        chat_room_repo_mock.find_by_id.return_value = room
        return room

    async def test_group_room_skips_block_check(
        self, service, block_repo_mock, redis_mock,
    ):
        """방 type 이 GROUP 이면 차단 체크 자체 skip — block_repo 호출 없음."""
        # 기본 mock 은 GROUP 방
        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="hi",
        )
        block_repo_mock.find_blocks_between.assert_not_called()
        # room:blocks 관련 Redis 호출도 없음
        assert redis_mock.sismember.call_count == 0 or all(
            "room:blocks" not in str(c) for c in redis_mock.sismember.call_args_list
        )

    async def test_direct_room_miss_through_no_blocks(
        self, service, block_repo_mock, direct_room_mock, redis_mock,
    ):
        """DIRECT 방 + 캐시 miss + DB 에 차단 없음 → __none__ sentinel SADD + 통과."""
        redis_mock.exists = AsyncMock(return_value=0)
        redis_mock.sismember = AsyncMock(return_value=False)
        block_repo_mock.find_blocks_between.return_value = []

        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="hi",
        )

        block_repo_mock.find_blocks_between.assert_awaited_once()
        # __none__ sentinel 이 pipeline 의 sadd 에 들어갔는지
        sadd_calls = [p for p in redis_mock._pipes if p.sadd.called]
        assert sadd_calls, "room:blocks 캐시 채우는 pipeline 호출이 없음"

    async def test_direct_room_sender_blocked_peer_raises(
        self, service, block_repo_mock, direct_room_mock, redis_mock,
    ):
        """sender→peer 방향 차단이 있으면 PermissionError."""
        redis_mock.exists = AsyncMock(return_value=1)  # 캐시 hit

        async def _sismember(key, member):
            return member == "U_A:U_B"
        redis_mock.sismember = AsyncMock(side_effect=_sismember)

        with pytest.raises(PermissionError, match="차단 관계"):
            await service.send_message(
                sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
                client_msg_id="cm-1", msg_type=MessageType.TEXT, content="hi",
            )

    async def test_direct_room_peer_blocked_sender_raises(
        self, service, block_repo_mock, direct_room_mock, redis_mock,
    ):
        """peer→sender 방향 차단도 거절 (상대가 나를 차단한 상태)."""
        redis_mock.exists = AsyncMock(return_value=1)

        async def _sismember(key, member):
            return member == "U_B:U_A"
        redis_mock.sismember = AsyncMock(side_effect=_sismember)

        with pytest.raises(PermissionError, match="차단 관계"):
            await service.send_message(
                sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
                client_msg_id="cm-1", msg_type=MessageType.TEXT, content="hi",
            )

    async def test_direct_room_peer_withdrawn_skips_check(
        self, service, block_repo_mock, chat_room_repo_mock,
    ):
        """상대가 탈퇴로 NULL 이면 차단 체크 skip (체크 의미 없음)."""
        chat_room_repo_mock.find_by_id.return_value = SimpleNamespace(
            chat_room_id="CR_1",
            type=ChatRoomType.DIRECT,
            creator_id="U_A",
            direct_user_a_id="U_A",
            direct_user_b_id=None,  # 상대 탈퇴
        )
        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="hi",
        )
        block_repo_mock.find_blocks_between.assert_not_called()
