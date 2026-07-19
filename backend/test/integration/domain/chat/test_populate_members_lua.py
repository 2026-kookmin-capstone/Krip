"""멤버 캐시 populate 의 generation 가드(populate_members.lua)를 실 Redis 로 검증.

regression: read-repair 는 cache miss 시 DB 멤버 스냅샷을 SADD 하는데, 그 사이 leave/kick 이
커밋(SREM + gen INCR)되면 커밋 전 스냅샷이 SREM 이후에 쓰여 제거된 멤버가 최대 TTL(600s) 동안
부활했다 — 강퇴/퇴장한 유저가 계속 메시지를 보내고 unread·FCM 을 받았다. populate 직전 캡처한
gen 과 현재 gen 이 다르면 SADD 를 건너뛰는지 실제 eval 로 확인한다 (단위 테스트는 Lua 호출
인자만 검증, 원자성/부활 차단 로직은 여기서).
"""
from pathlib import Path

import pytest

import app.core.chat.lua_script as lua_module
from app.core.chat.redis_key import (
    ROOM_MEMBERS_TTL,
    room_members_gen_key,
    room_members_key,
    unread_key,
)


pytestmark = pytest.mark.integration

_LUA_SRC = (
    Path(lua_module.__file__).parent / "lua" / "populate_members.lua"
).read_text(encoding="utf-8")

_ROOM = "R_pop"
_K = room_members_key(_ROOM)
_G = room_members_gen_key(_ROOM)


async def _populate(redis_hot, gen0, members):
    """read-repair 의 가드 populate 재현. gen0 은 DB 읽기 직전 캡처값."""
    script = redis_hot.register_script(_LUA_SRC)
    return int(await script(keys=[_K, _G], args=[gen0, ROOM_MEMBERS_TTL, *members]))


async def _remove(redis_hot, user):
    """_emit_member_removed 의 MULTI 재현: 영속 gen INCR + SREM + HDEL (원자)."""
    async with redis_hot.pipeline(transaction=True) as pipe:
        pipe.incr(_G)
        pipe.srem(_K, user)
        pipe.hdel(unread_key(user), _ROOM)
        await pipe.execute()


class TestPopulateMembersGuard:
    async def test_resurrection_blocked_when_removal_commits_mid_populate(self, redis_hot):
        """핵심 버그: gen 캡처 후 removal 이 커밋되면 stale populate 는 skip → 부활 없음."""
        await redis_hot.delete(_K, _G)

        gen0 = await redis_hot.get(_G) or "0"          # read-repair: gen 캡처 (부재→"0")
        snapshot = ["sender", "victim", "bob"]          # 커밋 전 DB 스냅샷 (victim 아직 활성)
        await _remove(redis_hot, "victim")              # 그 사이 victim leave 커밋 (gen INCR)
        applied = await _populate(redis_hot, gen0, snapshot)  # stale populate 시도

        assert applied == 0, "gen 불일치인데 populate 가 반영됨"
        assert not await redis_hot.sismember(_K, "victim"), "제거된 멤버가 부활함"
        await redis_hot.delete(_K, _G)

    async def test_removal_after_populate_still_removes(self, redis_hot):
        """populate 가 removal 보다 먼저면, 뒤이은 SREM 이 victim 을 제거한다."""
        await redis_hot.delete(_K, _G)

        gen0 = await redis_hot.get(_G) or "0"
        await _populate(redis_hot, gen0, ["sender", "victim", "bob"])
        await _remove(redis_hot, "victim")

        members = await redis_hot.smembers(_K)
        assert "victim" not in members and members == {"sender", "bob"}
        await redis_hot.delete(_K, _G)

    async def test_normal_populate_applies_and_sets_ttl(self, redis_hot):
        """경합이 없으면 members만 만료되고 generation fence는 영속한다."""
        await redis_hot.delete(_K, _G)
        await redis_hot.set(_G, 1)

        gen0 = await redis_hot.get(_G) or "0"
        applied = await _populate(redis_hot, gen0, ["sender", "bob"])

        assert applied == 1
        assert await redis_hot.smembers(_K) == {"sender", "bob"}
        assert 0 < await redis_hot.ttl(_K) <= ROOM_MEMBERS_TTL
        assert await redis_hot.ttl(_G) == -1
        await redis_hot.delete(_K, _G)

    async def test_populate_replaces_stale_set_no_merge(self, redis_hot):
        """가드 통과 시 기존 잔재를 DEL 후 채워 유령 멤버가 merge 로 남지 않는다."""
        await redis_hot.delete(_K, _G)
        await redis_hot.sadd(_K, "ghost")

        gen0 = await redis_hot.get(_G) or "0"
        await _populate(redis_hot, gen0, ["sender", "bob"])

        assert await redis_hot.smembers(_K) == {"sender", "bob"}
        await redis_hot.delete(_K, _G)

    async def test_any_membership_change_skips_populate(self, redis_hot):
        """gen 캡처 후 다중 멤버십 변경이 있으면 보수적으로 skip (다음 send 가 재적재)."""
        await redis_hot.delete(_K, _G)

        gen0 = await redis_hot.get(_G) or "0"
        await _remove(redis_hot, "v1")
        await _remove(redis_hot, "v2")
        applied = await _populate(redis_hot, gen0, ["sender", "v1", "v2", "bob"])

        assert applied == 0
        await redis_hot.delete(_K, _G)
