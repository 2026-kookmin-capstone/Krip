"""ChatService 단위 테스트 — 송신 11단계 핫패스 / 재시도 / dedupe / unread."""
from unittest.mock import AsyncMock

import pytest
from pymongo.errors import DuplicateKeyError

from app.core.chat.redis_keys import (
    DIRTY_CHAT_ROOM_KEY,
    RATE_LIMIT_THRESHOLD,
    dedupe_key,
    rate_msg_key,
)
from app.domain.chat.model.chat_message import MessageType
from app.domain.chat.service.exceptions import UpstreamError


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

        # RDB update_last_message 1회
        chat_room_repo_mock.update_last_message.assert_awaited_once()
        kwargs = chat_room_repo_mock.update_last_message.call_args.kwargs
        assert kwargs["chat_room_id"] == "CR_1"
        assert kwargs["server_seq"] == 7


# ──────────────────────────────────────────────────────────────────
# 멤버십 검증 (§5.1-2)
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestMembershipCheck:
    async def test_cache_hit_skips_rdb_load(self, service, redis_mock, chat_member_repo_mock):
        redis_mock.sismember = AsyncMock(return_value=True)

        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
        )

        chat_member_repo_mock.find_active_member_ids.assert_not_called()

    async def test_cache_miss_loads_all_members_and_sadd(
        self, service, redis_mock, chat_member_repo_mock,
    ):
        redis_mock.sismember = AsyncMock(return_value=False)
        chat_member_repo_mock.find_active_member_ids.return_value = ["U_A", "U_B"]

        await service.send_message(
            sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
            client_msg_id="cm-1", msg_type=MessageType.TEXT, content="x",
        )

        chat_member_repo_mock.find_active_member_ids.assert_awaited_once_with("CR_1")
        # SADD + EXPIRE pipeline 존재
        pipes_with_sadd = [p for p in redis_mock._pipes if p.sadd.called]
        assert pipes_with_sadd, "멤버 캐시 SADD pipeline 이 호출되지 않음"

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
    async def test_duplicate_client_msg_id_raises(
        self, service, redis_dedupe_mock,
    ):
        redis_dedupe_mock.set = AsyncMock(return_value=False)  # SET NX 실패 = 이미 있음

        with pytest.raises(ValueError, match="이미 처리된"):
            await service.send_message(
                sender_user_id="U_A", sender_session_id="WS_A", room_id="CR_1",
                client_msg_id="cm-dup", msg_type=MessageType.TEXT, content="x",
            )

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
# RDB UPDATE 실패 → dirty 큐
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRdbUpdateFailureDegrade:
    async def test_update_last_message_failure_adds_to_dirty_queue(
        self, service, chat_room_repo_mock, redis_mock, mock_session,
    ):
        from test.unit.domain.chat.chat_service.mock_factory import RaisingAsyncContextManager

        # begin_nested() 가 실패하는 SAVEPOINT 반환 → update_last_message 는 호출 전 롤백 유발
        mock_session.begin_nested.return_value = RaisingAsyncContextManager(
            RuntimeError("RDB connection reset"),
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
