"""Lua 스크립트 로더 / 레지스트리.

startup 시 1회 `.lua` 파일을 읽어 redis-py 의 `register_script()` 로 래핑.
`AsyncScript` 가 EVALSHA 우선 / NOSCRIPT 시 EVAL fallback 까지 자동 처리하므로
SHA 캐싱은 우리가 손대지 않는다.
"""
from pathlib import Path
from typing import Optional

from redis.asyncio import Redis
from redis.commands.core import AsyncScript

from app.core.instrumentation import instrument_lua_script


_LUA_DIR = Path(__file__).parent / "lua"


def _read(name: str) -> str:
    return (_LUA_DIR / name).read_text(encoding="utf-8")


class LuaScripts:
    """로드된 스크립트 보관. `load()` 호출 후 사용 가능."""

    def __init__(self) -> None:
        self.incr_fast: Optional[AsyncScript] = None
        self.recover_and_incr: Optional[AsyncScript] = None
        self.force_jump: Optional[AsyncScript] = None
        self.incr_with_ttl: Optional[AsyncScript] = None
        self.mark_read_unread: Optional[AsyncScript] = None
        self.increment_unread: Optional[AsyncScript] = None
        self.clear_unread_recovery_required: Optional[AsyncScript] = None
        self.get_unread_snapshot: Optional[AsyncScript] = None
        self.populate_members: Optional[AsyncScript] = None
        self.claim_dirty_rooms: Optional[AsyncScript] = None
        self.ack_dirty_rooms: Optional[AsyncScript] = None
        self.create_session: Optional[AsyncScript] = None
        self.heartbeat_session: Optional[AsyncScript] = None
        self.revoke_all_sessions: Optional[AsyncScript] = None

    def load(self, hot_client: Redis) -> None:
        """startup 1회. `instrument_lua_script` 로 감싸 호출 카운트 자동 부착."""
        self.incr_fast = instrument_lua_script(
            hot_client.register_script(_read("incr_fast.lua")), "incr_fast",
        )
        self.recover_and_incr = instrument_lua_script(
            hot_client.register_script(_read("recover_and_incr.lua")), "recover_and_incr",
        )
        self.force_jump = instrument_lua_script(
            hot_client.register_script(_read("force_jump.lua")), "force_jump",
        )
        self.incr_with_ttl = instrument_lua_script(
            hot_client.register_script(_read("incr_with_ttl.lua")), "incr_with_ttl",
        )
        self.mark_read_unread = instrument_lua_script(
            hot_client.register_script(_read("mark_read_unread.lua")), "mark_read_unread",
        )
        self.increment_unread = instrument_lua_script(
            hot_client.register_script(_read("increment_unread.lua")), "increment_unread",
        )
        self.clear_unread_recovery_required = instrument_lua_script(
            hot_client.register_script(_read("clear_unread_recovery_required.lua")),
            "clear_unread_recovery_required",
        )
        self.get_unread_snapshot = instrument_lua_script(
            hot_client.register_script(_read("get_unread_snapshot.lua")),
            "get_unread_snapshot",
        )
        self.populate_members = instrument_lua_script(
            hot_client.register_script(_read("populate_members.lua")), "populate_members",
        )
        self.claim_dirty_rooms = instrument_lua_script(
            hot_client.register_script(_read("claim_dirty_rooms.lua")), "claim_dirty_rooms",
        )
        self.ack_dirty_rooms = instrument_lua_script(
            hot_client.register_script(_read("ack_dirty_rooms.lua")), "ack_dirty_rooms",
        )
        self.create_session = instrument_lua_script(
            hot_client.register_script(_read("create_session.lua")), "create_session",
        )
        self.heartbeat_session = instrument_lua_script(
            hot_client.register_script(_read("heartbeat_session.lua")), "heartbeat_session",
        )
        self.revoke_all_sessions = instrument_lua_script(
            hot_client.register_script(_read("revoke_all_sessions.lua")),
            "revoke_all_sessions",
        )


lua_scripts = LuaScripts()
