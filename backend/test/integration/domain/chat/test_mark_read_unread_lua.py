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


async def _eval(redis_hot, key, room, residual, baseline):
    script = redis_hot.register_script(_LUA_SRC)
    return int(await script(keys=[key], args=[room, residual, baseline, _UNREAD_COUNT_CAP]))


class TestMarkReadUnreadLua:
    async def test_preserves_concurrent_increment(self, redis_hot):
        """baseline 이후 도착한 메시지의 HINCRBY 를 소거하지 않는다 (뱃지 손실 방지)."""
        key, room = "unread:it_lua_1", "R1"
        await redis_hot.delete(key)
        baseline = 0
        # count 스냅샷(residual=0) 이후 메시지 2건 도착 → HINCRBY 로 current=2
        await redis_hot.hincrby(key, room, 2)

        final = await _eval(redis_hot, key, room, residual=0, baseline=baseline)

        # 절대 HSET 이면 0 으로 소거됐을 값 — delta(2) 보존으로 2
        assert final == 2
        assert int(await redis_hot.hget(key, room)) == 2
        await redis_hot.delete(key)

    async def test_read_reduces_to_residual_when_no_concurrent(self, redis_hot):
        """동시 도착이 없으면 delta=0 → residual 그대로 (읽음이 정상 반영)."""
        key, room = "unread:it_lua_2", "R1"
        await redis_hot.delete(key)
        await redis_hot.hset(key, room, 5)  # 기존 미읽음 5

        final = await _eval(redis_hot, key, room, residual=1, baseline=5)

        assert final == 1
        await redis_hot.delete(key)

    async def test_full_read_clears_when_no_concurrent(self, redis_hot):
        key, room = "unread:it_lua_3", "R1"
        await redis_hot.delete(key)
        await redis_hot.hset(key, room, 3)

        final = await _eval(redis_hot, key, room, residual=0, baseline=3)

        assert final == 0
        await redis_hot.delete(key)

    async def test_caps_at_999(self, redis_hot):
        key, room = "unread:it_lua_4", "R1"
        await redis_hot.delete(key)

        final = await _eval(redis_hot, key, room, residual=1000, baseline=0)

        assert final == _UNREAD_COUNT_CAP  # 999
        await redis_hot.delete(key)
