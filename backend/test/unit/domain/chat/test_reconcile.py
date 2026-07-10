"""reconcile.recover_unread_for_user 단위 테스트.

unread self-heal 경로(재접속·Redis flush 후 복구). 절대 HSET 대신 baseline+delta Lua
(mark_read_unread)를 room 별로 호출해 count~write 창의 동시 HINCRBY 를 보존하는지, 부분 실패
시 hash 를 DEL 해 다음 재접속에서 재trigger 되게 하는지를 검증한다. (Lua 산술 자체는
test/integration/domain/chat/test_mark_read_unread_lua.py 에서 검증 — 여기선 orchestration.)
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.domain.chat.worker.reconcile as rc
from app.core.chat.redis_key import read_sync_key, unread_key


pytestmark = pytest.mark.unit

_UID = "U_recover"


class _FakeSession:
    active = False

    async def __aenter__(self):
        self.active = True
        return self

    async def __aexit__(self, *a):
        self.active = False
        return False


def _patches(*, last_reads, baselines, residuals, lua_side_effect, generation_error=None):
    """recover_unread_for_user 의 외부 의존성 패치 묶음 반환."""
    redis = MagicMock(name="redis")
    redis.hget = AsyncMock(side_effect=lambda key, field: baselines.get(field))
    session = _FakeSession()

    async def _get_generation(_key):
        assert session.active, "membership lock must cover generation capture"
        if generation_error is not None:
            raise generation_error
        return None

    redis.get = AsyncMock(side_effect=_get_generation)
    redis.delete = AsyncMock(return_value=1)

    async def _get_redis():
        return redis

    async def _count(*, chat_room_id, after_seq, limit):
        result = residuals[chat_room_id]
        if isinstance(result, BaseException):
            raise result
        return result

    msg_repo = MagicMock()
    msg_repo.count_after_seq = _count
    member_repo = MagicMock()
    member_repo.find_last_read_seqs = AsyncMock(return_value=last_reads)
    redis.member_repo = member_repo

    lua = MagicMock()
    lua.mark_read_unread = AsyncMock(side_effect=lua_side_effect)

    ctx = [
        patch.object(rc, "get_redis_client", _get_redis),
        patch.object(rc, "ChatMessageRepository", return_value=msg_repo),
        patch.object(rc, "ChatRoomMemberRepository", return_value=member_repo),
        patch.object(rc, "lua_scripts", lua),
        patch.object(rc, "_session_factory", lambda: session),
    ]
    return redis, lua, ctx


async def _run(ctx_managers):
    for c in ctx_managers:
        c.start()
    try:
        return await rc.recover_unread_for_user(_UID)
    finally:
        for c in reversed(ctx_managers):
            c.stop()


class TestRecoverUnread:
    async def test_passes_baseline_and_residual_to_lua_per_room(self):
        """room 별로 (room_id, residual, baseline, cap) 인자로 baseline+delta Lua 호출."""
        async def lua_stub(keys, args):
            _room, residual, _baseline, cap, read_seq, _allow_equal, _generation = args
            return [min(residual, cap), 1, read_seq]  # 스텁: residual 반영

        redis, lua, ctx = _patches(
            last_reads={"R1": 10, "R2": 20},
            baselines={"R1": "3", "R2": None},   # R2 는 baseline 부재 → 0 취급
            residuals={"R1": 5, "R2": 2},
            lua_side_effect=lua_stub,
        )
        counts = await _run(ctx)

        assert counts == {"R1": 5, "R2": 2}
        redis.member_repo.find_last_read_seqs.assert_awaited_once_with(
            _UID,
            room_ids=None,
            for_share=True,
        )
        # baseline 스냅샷(HGET)이 방마다 호출됐는지
        redis.hget.assert_any_await(unread_key(_UID), "R1")
        redis.hget.assert_any_await(unread_key(_UID), "R2")
        # Lua 인자에 baseline 이 정확히 전달됐는지 (부재는 0)
        calls = {c.kwargs["args"][0]: c.kwargs["args"] for c in lua.mark_read_unread.await_args_list}
        assert calls["R1"] == ["R1", 5, 3, rc.UNREAD_COUNT_CAP, 10, 1, 0]
        assert calls["R2"] == ["R2", 2, 0, rc.UNREAD_COUNT_CAP, 20, 1, 0]
        for call in lua.mark_read_unread.await_args_list:
            room_id = call.kwargs["args"][0]
            assert call.kwargs["keys"] == [
                unread_key(_UID), read_sync_key(_UID),
                rc.room_members_gen_key(room_id),
            ]

    async def test_caps_residual_snapshot_at_limit(self):
        """DB 잔여가 cap 을 넘으면 residual 스냅샷 단계에서 999 로 clamp 되어 전달된다."""
        async def lua_stub(keys, args):
            return [args[1], 1, args[4]]

        _redis, lua, ctx = _patches(
            last_reads={"R1": 0},
            baselines={"R1": None},
            residuals={"R1": 100_000},   # count_after_seq 원값 (min(raw, cap) 로 clamp 기대)
            lua_side_effect=lua_stub,
        )
        counts = await _run(ctx)

        assert counts == {"R1": rc.UNREAD_COUNT_CAP}
        assert lua.mark_read_unread.await_args_list[0].kwargs["args"][1] == rc.UNREAD_COUNT_CAP

    async def test_partial_lua_failure_deletes_hash(self):
        """Lua 반영 중 실패 → partial state 방지 위해 hash DEL 후 빈 dict 반환 (재trigger 유도)."""
        async def lua_flaky(keys, args):
            if args[0] == "R2":
                raise RuntimeError("redis blip")
            return [args[1], 1, args[4]]

        redis, _lua, ctx = _patches(
            last_reads={"R1": 0, "R2": 0},
            baselines={"R1": None, "R2": None},
            residuals={"R1": 1, "R2": 1},
            lua_side_effect=lua_flaky,
        )
        counts = await _run(ctx)

        assert counts == {}
        redis.delete.assert_awaited_once_with(unread_key(_UID))

    async def test_partial_count_failure_skips_lua_and_deletes_hashes(self):
        """방 하나의 Mongo count 실패도 partial HASH를 만들지 않고 전체 재시도한다."""
        redis, lua, ctx = _patches(
            last_reads={"R1": 10, "R2": 20},
            baselines={"R1": None, "R2": None},
            residuals={"R1": 1, "R2": RuntimeError("mongo blip")},
            lua_side_effect=lambda keys, args: [args[1], 1, args[4]],
        )

        counts = await _run(ctx)

        assert counts == {}
        lua.mark_read_unread.assert_not_awaited()
        redis.delete.assert_awaited_once_with(unread_key(_UID))

    async def test_generation_snapshot_failure_deletes_unread_only(self):
        redis, lua, ctx = _patches(
            last_reads={"R1": 10},
            baselines={"R1": None},
            residuals={"R1": 1},
            lua_side_effect=lambda keys, args: [args[1], 1, args[4]],
            generation_error=RuntimeError("redis blip"),
        )

        counts = await _run(ctx)

        assert counts == {}
        redis.hget.assert_not_awaited()
        lua.mark_read_unread.assert_not_awaited()
        redis.delete.assert_awaited_once_with(unread_key(_UID))

    async def test_no_active_rooms_skips(self):
        """활성 방이 없으면 Redis/Lua 를 건드리지 않고 빈 dict."""
        redis, lua, ctx = _patches(
            last_reads={},
            baselines={},
            residuals={},
            lua_side_effect=lambda keys, args: 0,
        )
        counts = await _run(ctx)

        assert counts == {}
        redis.hget.assert_not_awaited()
        lua.mark_read_unread.assert_not_awaited()
