"""SessionService 단위 테스트 — Redis 명령 시퀀스 + 한도 초과 revoke."""
import asyncio
from unittest.mock import AsyncMock

import pytest

from app.core.chat.redis_key import (
    sess_key,
    session_create_result_key,
    sessions_key,
    ws_route_key,
)


# ──────────────────────────────────────────────────────────────────
# create_session
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestCreateSession:
    async def test_issues_ws_prefixed_session_id(self, service):
        sid = await service.create_session(user_id="U_A", token_jti="jti_1")
        assert sid.startswith("WS_")

    async def test_prepares_ttl_keys_then_adds_session_via_lua(
        self, service, redis_mock, create_session_script,
    ):
        await service.create_session(user_id="U_A", token_jti="jti_1")

        assert len(redis_mock._pipes) >= 1
        p0 = redis_mock._pipes[0]
        assert p0.hset.called
        assert p0.expire.called
        assert p0.set.called
        assert not p0.zadd.called
        p0.execute.assert_awaited()
        create_session_script.assert_awaited_once()
        created_sid = create_session_script.call_args.kwargs["args"][0]
        assert create_session_script.call_args.kwargs["keys"] == [
            sessions_key("U_A"),
            session_create_result_key(created_sid),
        ]

    async def test_lua_selected_sessions_are_notified_then_route_is_deleted(
        self, service, redis_mock, fanout_mock, create_session_script,
    ):
        create_session_script.return_value = ["WS_old_1", "WS_old_2"]

        await service.create_session(user_id="U_A", token_jti="jti_1")

        assert fanout_mock.fan_out_to_session.await_count == 2
        redis_mock.delete.assert_any_await(ws_route_key("WS_old_1"))
        redis_mock.delete.assert_any_await(ws_route_key("WS_old_2"))

    async def test_fanout_failure_does_not_fail_created_session(
        self, service, redis_mock, fanout_mock, create_session_script,
    ):
        create_session_script.return_value = ["WS_old"]
        fanout_mock.fan_out_to_session.side_effect = RuntimeError("publish failed")

        sid = await service.create_session(user_id="U_A", token_jti="jti_1")

        assert sid.startswith("WS_")
        redis_mock.delete.assert_awaited_once_with(ws_route_key("WS_old"))

    async def test_cancellation_drains_all_revoked_session_cleanup(
        self, service, redis_mock, fanout_mock, create_session_script,
    ):
        create_session_script.return_value = ["WS_old_1", "WS_old_2"]
        fanout_started = asyncio.Event()
        release_fanout = asyncio.Event()

        async def delayed_fanout(*_args, **_kwargs):
            fanout_started.set()
            await release_fanout.wait()

        fanout_mock.fan_out_to_session.side_effect = delayed_fanout
        create_task = asyncio.create_task(service.create_session("U_A", "jti_1"))
        await fanout_started.wait()
        create_task.cancel()
        release_fanout.set()

        with pytest.raises(asyncio.CancelledError):
            await create_task

        assert fanout_mock.fan_out_to_session.await_count == 2
        redis_mock.delete.assert_any_await(ws_route_key("WS_old_1"))
        redis_mock.delete.assert_any_await(ws_route_key("WS_old_2"))

    async def test_cancellation_during_lua_drains_result_and_cleanup(
        self, service, redis_mock, fanout_mock, create_session_script,
    ):
        script_started = asyncio.Event()
        release_script = asyncio.Event()

        async def committed_script(**_kwargs):
            script_started.set()
            await release_script.wait()
            return ["WS_old"]

        create_session_script.side_effect = committed_script
        create_task = asyncio.create_task(service.create_session("U_A", "jti_1"))
        await script_started.wait()
        create_task.cancel()
        release_script.set()

        with pytest.raises(asyncio.CancelledError):
            await create_task

        fanout_mock.fan_out_to_session.assert_awaited_once()
        redis_mock.delete.assert_awaited_once_with(ws_route_key("WS_old"))

    async def test_cancelled_lost_lua_response_retries_then_finalizes(
        self, service, redis_mock, fanout_mock, create_session_script,
    ):
        script_started = asyncio.Event()
        lose_response = asyncio.Event()

        calls = 0

        async def committed_but_lost(**_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                script_started.set()
                await lose_response.wait()
                raise TimeoutError("committed response lost")
            return ["WS_old"]

        create_session_script.side_effect = committed_but_lost
        create_task = asyncio.create_task(service.create_session("U_A", "jti_1"))
        await script_started.wait()
        create_task.cancel()
        lose_response.set()

        with pytest.raises(asyncio.CancelledError):
            await create_task

        assert create_session_script.await_count == 2
        fanout_mock.fan_out_to_session.assert_awaited_once()
        redis_mock.delete.assert_awaited_once_with(ws_route_key("WS_old"))

    async def test_indeterminate_lua_failure_does_not_compensate_session(
        self, service, redis_mock, create_session_script,
    ):
        create_session_script.side_effect = TimeoutError("response lost")

        with pytest.raises(TimeoutError, match="response lost"):
            await service.create_session(user_id="U_A", token_jti="jti_1")

        assert len(redis_mock._pipes) == 1
        redis_mock.delete.assert_not_awaited()
        assert create_session_script.await_count == 3

    async def test_lost_lua_response_recovers_idempotent_result(
        self, service, fanout_mock, create_session_script,
    ):
        create_session_script.side_effect = [
            TimeoutError("response lost"),
            ["WS_old"],
        ]

        sid = await service.create_session("U_A", "jti_1")

        assert sid.startswith("WS_")
        assert create_session_script.await_count == 2
        fanout_mock.fan_out_to_session.assert_awaited_once()

    async def test_heartbeat_returns_atomic_membership_result(
        self, service, heartbeat_script,
    ):
        heartbeat_script.return_value = 0

        alive = await service.heartbeat("WS_dead", "U_A")

        assert alive is False


# ──────────────────────────────────────────────────────────────────
# heartbeat
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestHeartbeat:
    async def test_extends_three_keys_atomically(
        self, service, redis_mock, heartbeat_script,
    ):
        assert await service.heartbeat(session_id="WS_1", user_id="U_A") is True

        heartbeat_script.assert_awaited_once()
        assert heartbeat_script.call_args.kwargs["keys"] == [
            sess_key("WS_1"),
            ws_route_key("WS_1"),
            sessions_key("U_A"),
        ]
        assert heartbeat_script.call_args.kwargs["client"] is redis_mock


# ──────────────────────────────────────────────────────────────────
# session_exists / get_user_id / update_token_jti
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestSimpleAccessors:
    async def test_session_exists_true_when_key_present(self, service, redis_mock):
        redis_mock.exists = AsyncMock(return_value=1)
        assert await service.session_exists("WS_1") is True

    async def test_session_exists_false_when_key_absent(self, service, redis_mock):
        redis_mock.exists = AsyncMock(return_value=0)
        assert await service.session_exists("WS_1") is False

    async def test_get_user_id_returns_value(self, service, redis_mock):
        redis_mock.hget = AsyncMock(return_value="U_A")
        assert await service.get_user_id("WS_1") == "U_A"

    async def test_get_user_id_returns_none_when_missing(self, service, redis_mock):
        redis_mock.hget = AsyncMock(return_value=None)
        assert await service.get_user_id("WS_ghost") is None

    async def test_update_token_jti_writes_hash_field(self, service, redis_mock):
        await service.update_token_jti("WS_1", "new_jti")

        redis_mock.hset.assert_awaited_once()
        args, _ = redis_mock.hset.call_args
        assert args == (sess_key("WS_1"), "token_jti", "new_jti")


# ──────────────────────────────────────────────────────────────────
# terminate_session
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestTerminate:
    async def test_deletes_sess_ws_route_and_zrem_sessions(self, service, redis_mock):
        await service.terminate_session("WS_1", "U_A")

        assert len(redis_mock._pipes) == 1
        p = redis_mock._pipes[0]

        # delete 는 sess + ws_route 두 키
        delete_keys = [c.args[0] for c in p.delete.call_args_list]
        assert sess_key("WS_1") in delete_keys
        assert ws_route_key("WS_1") in delete_keys

        # zrem 은 sessions 에서 session_id 제거
        p.zrem.assert_called_once_with(sessions_key("U_A"), "WS_1")


# ──────────────────────────────────────────────────────────────────
# revoke_all_sessions — 회원 탈퇴 등 전수 강제 종료
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRevokeAllSessions:
    """Tests for SessionService.revoke_all_sessions."""

    async def test_returns_zero_when_user_has_no_active_sessions(
        self, service, redis_mock, fanout_mock,
    ):
        """오프라인 유저 — 빈 ZSET → 0 반환, 부수효과 없음."""
        redis_mock.zrange = AsyncMock(return_value=[])

        count = await service.revoke_all_sessions(user_id="U_A")

        assert count == 0
        fanout_mock.fan_out_to_session.assert_not_awaited()
        # pipeline 도 호출 안 됨 (early return)
        for p in redis_mock._pipes:
            assert not p.delete.called

    async def test_emits_session_revoked_event_for_each_session(
        self, service, redis_mock, fanout_mock,
    ):
        """각 세션마다 session_revoked 이벤트 직송. node_channel 모드에선 ws_route 라우팅."""
        redis_mock.zrange = AsyncMock(return_value=["WS_1", "WS_2", "WS_3"])

        count = await service.revoke_all_sessions(user_id="U_A")

        assert count == 3
        assert fanout_mock.fan_out_to_session.await_count == 3
        for idx, c in enumerate(fanout_mock.fan_out_to_session.call_args_list):
            sid = f"WS_{idx + 1}"
            assert c.args[0] == sid
            assert c.args[1] == {"type": "session_revoked", "session_id": sid}

    async def test_pipeline_deletes_sess_ws_route_and_sessions_zset(
        self, service, redis_mock,
    ):
        """한 pipeline 안에서 모든 sess: / ws_route: + sessions:{uid} 통째로 DEL."""
        redis_mock.zrange = AsyncMock(return_value=["WS_1", "WS_2"])

        await service.revoke_all_sessions(user_id="U_A")

        # 마지막 pipeline 이 revoke 처리 — fanout 호출 뒤
        revoke_pipe = redis_mock._pipes[-1]
        revoke_pipe.execute.assert_awaited()

        # delete 인자 모음 — 단일 DEL 에 (sess, ws_route) 2개 묶이는 케이스 + sessions DEL
        all_delete_args = [
            arg for c in revoke_pipe.delete.call_args_list for arg in c.args
        ]
        assert sess_key("WS_1") in all_delete_args
        assert sess_key("WS_2") in all_delete_args
        assert ws_route_key("WS_1") in all_delete_args
        assert ws_route_key("WS_2") in all_delete_args
        assert sessions_key("U_A") in all_delete_args
