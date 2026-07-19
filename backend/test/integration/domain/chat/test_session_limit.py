"""PHASE_1 통합 체크리스트 — "동일 유저 11 번째 로그인 → 가장 오래된 세션 revoke".

원자 create-session Lua의 동시 limit, idempotent result, revoke cleanup이 실제 Redis에서
정확히 동작하는지 검증한다.
"""
import asyncio

import pytest

from app.core.chat.lua_script import lua_scripts
from app.core.chat.redis_key import (
    MAX_SESSIONS_PER_USER,
    SESSION_TTL,
    sess_key,
    session_create_result_key,
    session_revoke_generation_key,
    sessions_key,
    ws_route_key,
)


pytestmark = pytest.mark.integration


class TestSessionLimitOnRealRedis:
    async def test_create_retry_rechecks_generation_after_revoke(
        self, session_service, redis_hot, monkeypatch,
    ):
        user_id = "USER_CREATE_RESPONSE_LOSS_REVOKE"
        generation = await session_service.get_revoke_generation(user_id)
        real_script = lua_scripts.create_session
        assert real_script is not None
        calls = 0

        async def committed_then_revoked(**kwargs):
            nonlocal calls
            calls += 1
            result = await real_script(**kwargs)
            if calls == 1:
                await session_service.revoke_all_sessions(user_id)
                raise TimeoutError("create response lost after commit")
            return result

        monkeypatch.setattr(lua_scripts, "create_session", committed_then_revoked)

        with pytest.raises(RuntimeError, match="revoke generation"):
            await session_service.create_session(
                user_id,
                "jti",
                expected_revoke_generation=generation,
            )
        assert calls == 2
        assert await redis_hot.zcard(sessions_key(user_id)) == 0

    async def test_revoke_retry_recovers_committed_result_after_response_loss(
        self, session_service, redis_hot, chat_fanout_stub, monkeypatch,
    ):
        user_id = "USER_REVOKE_RESPONSE_LOSS"
        session_id = await session_service.create_session(user_id, "jti")
        real_script = lua_scripts.revoke_all_sessions
        assert real_script is not None
        calls = 0

        async def committed_but_lost(**kwargs):
            nonlocal calls
            calls += 1
            result = await real_script(**kwargs)
            if calls == 1:
                raise TimeoutError("response lost after commit")
            return result

        monkeypatch.setattr(lua_scripts, "revoke_all_sessions", committed_but_lost)

        assert await session_service.revoke_all_sessions(user_id) == 1
        assert calls == 2
        assert await redis_hot.exists(sess_key(session_id)) == 0
        assert await redis_hot.exists(ws_route_key(session_id)) == 0
        chat_fanout_stub.fan_out_to_session.assert_awaited_once()

    async def test_revoke_generation_rejects_a_create_started_before_revoke(
        self, session_service, redis_hot,
    ):
        user_id = "USER_CREATE_REVOKE_RACE"
        generation = await session_service.get_revoke_generation(user_id)

        await session_service.revoke_all_sessions(user_id)

        with pytest.raises(RuntimeError, match="revoke generation"):
            await session_service.create_session(
                user_id,
                "stale-create",
                expected_revoke_generation=generation,
            )
        assert await redis_hot.zcard(sessions_key(user_id)) == 0
        assert await redis_hot.get(session_revoke_generation_key(user_id)) == "1"

    async def test_revoke_all_removes_authoritative_state_when_fanout_fails(
        self, session_service, redis_hot, chat_fanout_stub,
    ):
        user_id = "USER_REVOKE_FANOUT_FAILURE"
        session_ids = [
            await session_service.create_session(user_id, f"jti-{index}")
            for index in range(2)
        ]
        chat_fanout_stub.fan_out_to_session.side_effect = RuntimeError("publish failed")

        count = await session_service.revoke_all_sessions(user_id)

        assert count == 2
        assert await redis_hot.exists(sessions_key(user_id)) == 0
        for session_id in session_ids:
            assert await redis_hot.exists(sess_key(session_id)) == 0
            assert await redis_hot.exists(ws_route_key(session_id)) == 0
            assert await session_service.heartbeat(session_id, user_id) is False

    async def test_create_session_lua_retry_returns_committed_result(
        self, session_service, redis_hot, chat_fanout_stub,
    ):
        user_id = "USER_IDEMPOTENT_LIMIT"
        for i in range(MAX_SESSIONS_PER_USER):
            await session_service.create_session(user_id, f"existing-{i}")
            await asyncio.sleep(0.003)

        sid = await session_service.create_session(user_id, "new")
        original_victim = chat_fanout_stub.fan_out_to_session.call_args.args[0]
        sessions_before_retry = await redis_hot.zrange(sessions_key(user_id), 0, -1)
        fanout_count_before_retry = chat_fanout_stub.fan_out_to_session.await_count
        script = lua_scripts.create_session
        assert script is not None
        retried_result = await script(
            keys=[
                sessions_key(user_id),
                session_create_result_key(sid),
                session_revoke_generation_key(user_id),
            ],
            args=[sid, 0, 0, MAX_SESSIONS_PER_USER, SESSION_TTL, 0],
            client=redis_hot,
        )

        assert retried_result == [original_victim]
        assert await redis_hot.zcard(sessions_key(user_id)) == MAX_SESSIONS_PER_USER
        assert await redis_hot.zrange(sessions_key(user_id), 0, -1) == sessions_before_retry
        assert chat_fanout_stub.fan_out_to_session.await_count == fanout_count_before_retry

    async def test_concurrent_creates_do_not_revoke_below_limit(
        self, session_service, redis_hot, chat_fanout_stub,
    ):
        user_id = "USER_CONCURRENT_LIMIT"
        existing = []
        for i in range(MAX_SESSIONS_PER_USER):
            existing.append(await session_service.create_session(user_id, f"existing-{i}"))
            await asyncio.sleep(0.003)

        first_sid, second_sid = await asyncio.gather(
            session_service.create_session(user_id, "concurrent-1"),
            session_service.create_session(user_id, "concurrent-2"),
        )

        assert await redis_hot.zcard(sessions_key(user_id)) == MAX_SESSIONS_PER_USER
        assert await redis_hot.exists(sess_key(first_sid)) == 1
        assert await redis_hot.exists(sess_key(second_sid)) == 1
        existing_alive = await asyncio.gather(*(
            redis_hot.exists(sess_key(sid)) for sid in existing
        ))
        assert sum(existing_alive) == MAX_SESSIONS_PER_USER - 2
        assert chat_fanout_stub.fan_out_to_session.await_count == 2

    async def test_exceeding_limit_revokes_oldest_session(
        self, session_service, redis_hot, chat_fanout_stub,
    ):
        user_id = "USER_LIMIT"
        sids: list[str] = []

        # MAX+1 번 create_session. sleep 은 ZSET score (만료시각 ms) 를 강제로
        # 서로 다르게 만들기 위함 — 같은 ms 에 몰리면 "가장 오래된" 이 member 문자열
        # 순으로 결정되어 테스트 의도와 엇갈릴 수 있다.
        for i in range(MAX_SESSIONS_PER_USER + 1):
            sid = await session_service.create_session(user_id, f"jti-{i}")
            sids.append(sid)
            await asyncio.sleep(0.003)

        assert await redis_hot.zcard(sessions_key(user_id)) == MAX_SESSIONS_PER_USER

        oldest_sid = sids[0]

        assert await redis_hot.exists(sess_key(oldest_sid)) == 0
        assert await redis_hot.exists(ws_route_key(oldest_sid)) == 0
        assert await redis_hot.zscore(sessions_key(user_id), oldest_sid) is None

        revoked_calls = [
            call for call in chat_fanout_stub.fan_out_to_session.await_args_list
            if call.args[0] == oldest_sid
        ]
        assert len(revoked_calls) == 1
        assert revoked_calls[0].args[1] == {
            "type": "session_revoked",
            "session_id": oldest_sid,
        }

        for sid in sids[1:]:
            assert await redis_hot.exists(sess_key(sid)) == 1
            assert await redis_hot.exists(ws_route_key(sid)) == 1
            assert await redis_hot.zscore(sessions_key(user_id), sid) is not None

    async def test_under_limit_does_not_revoke(
        self, session_service, redis_hot, chat_fanout_stub,
    ):
        """MAX 번 로그인까지는 revoke 발생 없음."""
        user_id = "USER_UNDER"
        for i in range(MAX_SESSIONS_PER_USER):
            await session_service.create_session(user_id, f"jti-{i}")
            await asyncio.sleep(0.003)

        assert await redis_hot.zcard(sessions_key(user_id)) == MAX_SESSIONS_PER_USER
        chat_fanout_stub.fan_out_to_session.assert_not_awaited()
