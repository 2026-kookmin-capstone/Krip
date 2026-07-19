"""dirty room reconcile claim/ACK Lua를 실제 Redis에서 검증."""
import asyncio
from pathlib import Path

import pytest

import app.core.chat.lua_script as lua_module


pytestmark = pytest.mark.integration

_CLAIM_LUA_SRC = (
    Path(lua_module.__file__).parent / "lua" / "claim_dirty_rooms.lua"
).read_text(encoding="utf-8")
_ACK_LUA_SRC = (
    Path(lua_module.__file__).parent / "lua" / "ack_dirty_rooms.lua"
).read_text(encoding="utf-8")


async def _claim(
    redis_hot, dirty: str, processing: str, owner: str, deferred: str,
    batch_size: int, lease_ms: int, token: str,
):
    script = redis_hot.register_script(_CLAIM_LUA_SRC)
    result = await script(
        keys=[dirty, processing, owner, deferred],
        args=[batch_size, lease_ms, token],
    )
    return bool(int(result[0])), result[1:]


async def _ack(
    redis_hot, dirty: str, processing: str, owner: str, deferred: str,
    token: str, *rooms,
):
    script = redis_hot.register_script(_ACK_LUA_SRC)
    return await script(
        keys=[processing, owner, deferred, dirty],
        args=[token, *rooms],
    )


class TestClaimDirtyRoomsLua:
    @staticmethod
    async def _clear(redis_hot, *keys):
        await redis_hot.delete(*keys)

    async def test_moves_new_dirty_room_to_processing(self, redis_hot):
        keys = (
            "it:dirty:claim:new", "it:dirty:claim:processing:new",
            "it:dirty:claim:owner:new", "it:dirty:claim:deferred:new",
        )
        dirty, processing, owner, deferred = keys
        await self._clear(redis_hot, *keys)
        await redis_hot.sadd(dirty, "R1")

        more, claimed = await _claim(
            redis_hot, *keys, batch_size=500, lease_ms=5000, token="A",
        )

        assert more is False
        assert claimed == ["R1"]
        assert await redis_hot.smembers(dirty) == set()
        assert await redis_hot.zscore(processing, "R1") is not None
        assert await redis_hot.hget(owner, "R1") == "A"
        await self._clear(redis_hot, *keys)

    async def test_defers_new_dirty_copy_until_current_owner_ack(self, redis_hot):
        keys = (
            "it:dirty:claim:repeat", "it:dirty:claim:processing:repeat",
            "it:dirty:claim:owner:repeat", "it:dirty:claim:deferred:repeat",
        )
        dirty, processing, owner, deferred = keys
        await self._clear(redis_hot, *keys)
        await redis_hot.zadd(processing, {"R1": 9_999_999_999_999})
        await redis_hot.hset(owner, "R1", "A")
        await redis_hot.sadd(dirty, "R1")

        more, claimed = await _claim(
            redis_hot, *keys, batch_size=500, lease_ms=5000, token="B",
        )

        assert more is False
        assert claimed == []
        assert await redis_hot.smembers(dirty) == set()
        assert await redis_hot.smembers(deferred) == {"R1"}
        assert await _ack(redis_hot, *keys, "A", "R1") == 1
        assert await redis_hot.smembers(deferred) == set()
        assert await redis_hot.smembers(dirty) == {"R1"}
        await self._clear(redis_hot, *keys)

    async def test_stale_owner_cannot_ack_reclaimed_generation(self, redis_hot):
        keys = (
            "it:dirty:claim:aba", "it:dirty:claim:processing:aba",
            "it:dirty:claim:owner:aba", "it:dirty:claim:deferred:aba",
        )
        dirty, processing, owner, _deferred = keys
        await self._clear(redis_hot, *keys)
        await redis_hot.sadd(dirty, "R1")

        assert await _claim(redis_hot, *keys, 1, 10, "A") == (False, ["R1"])
        await asyncio.sleep(0.02)
        assert await _claim(redis_hot, *keys, 1, 100, "B") == (False, ["R1"])

        assert await _ack(redis_hot, *keys, "A", "R1") == 0
        assert await redis_hot.hget(owner, "R1") == "B"
        assert await redis_hot.zscore(processing, "R1") is not None
        assert await _ack(redis_hot, *keys, "B", "R1") == 1
        assert await redis_hot.zscore(processing, "R1") is None
        await self._clear(redis_hot, *keys)

    async def test_active_copies_cannot_starve_fresh_dirty(self, redis_hot):
        keys = (
            "it:dirty:claim:bounded", "it:dirty:claim:processing:bounded",
            "it:dirty:claim:owner:bounded", "it:dirty:claim:deferred:bounded",
        )
        dirty, processing, owner, deferred = keys
        await self._clear(redis_hot, *keys)
        blockers = {f"ACTIVE{i}": 9_999_999_999_999 for i in range(100)}
        await redis_hot.zadd(processing, blockers)
        await redis_hot.hset(owner, mapping={room: "old" for room in blockers})
        await redis_hot.sadd(dirty, *blockers, "FRESH")

        claimed_all: list[str] = []
        for attempt in range(30):
            more, claimed = await _claim(
                redis_hot, *keys, batch_size=2, lease_ms=5000,
                token=f"worker-{attempt}",
            )
            claimed_all.extend(claimed)
            if "FRESH" in claimed_all:
                break
            assert more is True

        assert "FRESH" in claimed_all
        assert await redis_hot.scard(deferred) > 0
        await self._clear(redis_hot, *keys)

    async def test_ready_backlog_cannot_starve_expired_claim(self, redis_hot):
        keys = (
            "it:dirty:claim:both", "it:dirty:claim:processing:both",
            "it:dirty:claim:owner:both", "it:dirty:claim:deferred:both",
        )
        dirty, processing, owner, _deferred = keys
        await self._clear(redis_hot, *keys)
        await redis_hot.zadd(processing, {"EXPIRED": 0})
        await redis_hot.hset(owner, "EXPIRED", "dead-owner")
        await redis_hot.sadd(dirty, "FRESH")

        _more, claimed = await _claim(
            redis_hot, *keys, batch_size=2, lease_ms=5000, token="new-owner",
        )

        assert set(claimed) == {"EXPIRED", "FRESH"}
        assert await redis_hot.hget(owner, "EXPIRED") == "new-owner"
        await self._clear(redis_hot, *keys)
