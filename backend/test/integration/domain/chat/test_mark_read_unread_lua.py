"""mark_read 의 unread 재계산 Lua(_MARK_READ_UNREAD_LUA)를 실 Redis 로 검증.

regression: 절대값 HSET 은 count~write 창에서 도착한 메시지의 HINCRBY 를 소거해 뱃지를
영구히 잃었다. baseline 이후 증가분(delta)을 residual 에 더해 보존하는지, cap 이 적용되는지
실제 Redis eval 로 확인한다 (단위 테스트는 eval 인자만 검증, 값 로직은 여기서).
"""
from pathlib import Path

import pytest

import app.core.chat.lua_script as lua_module
from app.domain.chat.service.room import _UNREAD_COUNT_CAP


pytestmark = pytest.mark.integration

# 프로덕션과 동일한 .lua 파일을 register_script(EVALSHA) 로 로드해 검증.
_LUA_SRC = (
    Path(lua_module.__file__).parent / "lua" / "mark_read_unread.lua"
).read_text(encoding="utf-8")


async def _eval(
    redis_hot, key, cursor_key, room, residual, baseline, read_seq, *,
    allow_equal=0, expected_generation=0,
):
    script = redis_hot.register_script(_LUA_SRC)
    generation_key = f"room:members:gen:{room}"
    result = await script(
        keys=[key, cursor_key, generation_key],
        args=[
            room, residual, baseline, _UNREAD_COUNT_CAP, read_seq, allow_equal,
            expected_generation,
        ],
    )
    return tuple(int(value) for value in result)


class TestMarkReadUnreadLua:
    async def test_preserves_concurrent_increment(self, redis_hot):
        """baseline 이후 도착한 메시지의 HINCRBY 를 소거하지 않는다 (뱃지 손실 방지)."""
        key, cursor_key, room = "unread:it_lua_1", "unread:read_seq:it_lua_1", "R1"
        await redis_hot.delete(key, cursor_key)
        baseline = 0
        # count 스냅샷(residual=0) 이후 메시지 2건 도착 → HINCRBY 로 current=2
        await redis_hot.hincrby(key, room, 2)

        final, applied, effective_seq = await _eval(
            redis_hot, key, cursor_key, room,
            residual=0, baseline=baseline, read_seq=10,
        )

        # 절대 HSET 이면 0 으로 소거됐을 값 — delta(2) 보존으로 2
        assert final == 2
        assert applied == 1
        assert effective_seq == 10
        assert int(await redis_hot.hget(key, room)) == 2
        await redis_hot.delete(key, cursor_key)

    async def test_read_reduces_to_residual_when_no_concurrent(self, redis_hot):
        """동시 도착이 없으면 delta=0 → residual 그대로 (읽음이 정상 반영)."""
        key, cursor_key, room = "unread:it_lua_2", "unread:read_seq:it_lua_2", "R1"
        await redis_hot.delete(key, cursor_key)
        await redis_hot.hset(key, room, 5)  # 기존 미읽음 5

        final, _, _ = await _eval(
            redis_hot, key, cursor_key, room, residual=1, baseline=5, read_seq=10,
        )

        assert final == 1
        await redis_hot.delete(key, cursor_key)

    async def test_full_read_clears_when_no_concurrent(self, redis_hot):
        key, cursor_key, room = "unread:it_lua_3", "unread:read_seq:it_lua_3", "R1"
        await redis_hot.delete(key, cursor_key)
        await redis_hot.hset(key, room, 3)

        final, _, _ = await _eval(
            redis_hot, key, cursor_key, room, residual=0, baseline=3, read_seq=10,
        )

        assert final == 0
        await redis_hot.delete(key, cursor_key)

    async def test_caps_at_999(self, redis_hot):
        key, cursor_key, room = "unread:it_lua_4", "unread:read_seq:it_lua_4", "R1"
        await redis_hot.delete(key, cursor_key)

        final, _, _ = await _eval(
            redis_hot, key, cursor_key, room, residual=1000, baseline=0, read_seq=10,
        )

        assert final == _UNREAD_COUNT_CAP  # 999
        await redis_hot.delete(key, cursor_key)

    async def test_ignores_late_lower_read_seq(self, redis_hot):
        key, cursor_key, room = "unread:it_lua_5", "unread:read_seq:it_lua_5", "R1"
        await redis_hot.delete(key, cursor_key)
        await redis_hot.hset(key, room, 5)

        first = await _eval(
            redis_hot, key, cursor_key, room, residual=0, baseline=5, read_seq=20,
        )
        late = await _eval(
            redis_hot, key, cursor_key, room, residual=3, baseline=0, read_seq=10,
        )

        assert first == (0, 1, 20)
        assert late == (0, 0, 20)
        assert int(await redis_hot.hget(key, room)) == 0
        assert int(await redis_hot.hget(cursor_key, room)) == 20
        await redis_hot.delete(key, cursor_key)

    async def test_equal_seq_is_idempotent_unless_recovery_recalculates(
        self, redis_hot,
    ):
        key, cursor_key, room = "unread:it_lua_6", "unread:read_seq:it_lua_6", "R1"
        await redis_hot.delete(key, cursor_key)

        first = await _eval(
            redis_hot, key, cursor_key, room, residual=0, baseline=0, read_seq=20,
        )
        await redis_hot.hincrby(key, room, 1)
        duplicate = await _eval(
            redis_hot, key, cursor_key, room, residual=0, baseline=0, read_seq=20,
        )
        await redis_hot.hdel(key, room)
        recovery = await _eval(
            redis_hot, key, cursor_key, room, residual=1, baseline=0, read_seq=20,
            allow_equal=1,
        )

        assert first == (0, 1, 20)
        # 동일 seq 재시도는 unread는 no-op이지만 room fanout 재시도를 허용하는 status=2.
        assert duplicate == (1, 2, 20)
        assert recovery == (1, 1, 20)
        await redis_hot.delete(key, cursor_key)

    async def test_membership_generation_change_blocks_delayed_read(self, redis_hot):
        """read commit 뒤 leave gen 증가가 끝나면 지연 Lua가 unread를 부활시키지 않는다."""
        key = "unread:it_lua_7"
        cursor_key = "unread:read_seq:it_lua_7"
        room = "R_LEAVE"
        generation_key = f"room:members:gen:{room}"
        await redis_hot.delete(key, cursor_key, generation_key)
        await redis_hot.hset(key, room, 3)

        # read는 generation=0에서 시작했지만 leave cleanup이 gen=1 + unread HDEL 완료.
        await redis_hot.set(generation_key, 1)
        await redis_hot.hdel(key, room)
        result = await _eval(
            redis_hot, key, cursor_key, room,
            residual=0, baseline=3, read_seq=20, expected_generation=0,
        )

        assert result == (0, 3, 20)
        assert await redis_hot.hget(key, room) is None
        assert await redis_hot.hget(cursor_key, room) is None
        await redis_hot.delete(key, cursor_key, generation_key)
