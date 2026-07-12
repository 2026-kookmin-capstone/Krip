"""WS 세션의 Redis 상태 관리.

키:
- `sess:{session_id}`     HASH    user_id, node_id, token_jti, connected_at (TTL 90s)
- `sessions:{user_id}`    ZSET    score=만료시각ms, member=session_id
- `ws_route:{session_id}` STRING  node_id (TTL 90s, fan_out_to_session 라우팅용)

ZSET 의 score 가 만료시각이라 `ZREMRANGEBYSCORE -inf <now>` 한 번으로 죽은 세션 청소 — 자가 치유.
"""
import asyncio
import time

from app.config.setting import settings
from app.core.chat.lua_script import lua_scripts
from app.core.chat.redis_key import (
    MAX_SESSIONS_PER_USER,
    SESSION_TTL,
    sess_key,
    session_create_result_key,
    sessions_key,
    ws_route_key,
)
from app.core.logger import get_logger
from app.core.redis import get_redis_client
from app.domain.chat.service.fanout import FanoutService
from app.util.id_generator import generate_session_id


logger = get_logger("chat.session")


class SessionService:
    """WS 세션 생명주기 — 생성 / heartbeat / 종료 / 한도 초과 revoke."""

    def __init__(self, fanout_service: FanoutService):
        self._fanout = fanout_service

    @staticmethod
    def _now_ms() -> int:
        return int(time.time() * 1000)

    @classmethod
    def _expires_ms(cls, now_ms: int | None = None) -> int:
        if now_ms is None:
            now_ms = cls._now_ms()
        return now_ms + SESSION_TTL * 1000

    async def create_session(self, user_id: str, token_jti: str) -> str:
        """WS 연결 시 호출 — 새 session_id 발급 후 Redis 3키 + 한도 체크."""
        session_id = generate_session_id()
        now_ms = self._now_ms()
        expires_ms = now_ms + SESSION_TTL * 1000

        redis = await get_redis_client()
        pipe = redis.pipeline(transaction=True)
        pipe.hset(sess_key(session_id), mapping={
            "user_id": user_id,
            "node_id": settings.NODE_ID,
            "token_jti": token_jti,
            "connected_at": str(now_ms),
        })
        pipe.expire(sess_key(session_id), SESSION_TTL)
        pipe.set(ws_route_key(session_id), settings.NODE_ID, ex=SESSION_TTL)
        try:
            await pipe.execute()
        except BaseException:
            try:
                cleanup = redis.pipeline(transaction=True)
                cleanup.delete(sess_key(session_id), ws_route_key(session_id))
                await cleanup.execute()
            except Exception as cleanup_exc:
                logger.warning(
                    "실패한 세션 준비 cleanup 실패: session_id={}, err={}",
                    session_id, cleanup_exc,
                )
            raise

        script = lua_scripts.create_session
        if script is None:
            raise RuntimeError("create_session Lua script가 로드되지 않았습니다.")
        script_args = {
            "keys": [
                sessions_key(user_id),
                session_create_result_key(session_id),
            ],
            "args": [
                session_id,
                expires_ms,
                now_ms,
                MAX_SESSIONS_PER_USER,
                SESSION_TTL,
            ],
            "client": redis,
        }
        cancellation_seen = [False]
        for attempt in range(3):
            script_task = asyncio.create_task(script(**script_args))
            try:
                revoked_session_ids = list(await self._drain_task(
                    script_task, cancellation_seen,
                ))
                break
            except Exception:
                if attempt == 2:
                    if cancellation_seen[0]:
                        raise asyncio.CancelledError
                    raise
        else:  # pragma: no cover - range above always exits or raises
            raise RuntimeError("create_session Lua 결과를 확인하지 못했습니다.")

        finalize_task = asyncio.create_task(
            self._finalize_revoked_sessions(user_id, revoked_session_ids),
        )
        await self._drain_task(finalize_task, cancellation_seen)
        if cancellation_seen[0]:
            raise asyncio.CancelledError
        return session_id

    @staticmethod
    async def _drain_task(task: asyncio.Task, cancellation_seen: list[bool]):
        while True:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError:
                if task.cancelled():
                    raise
                cancellation_seen[0] = True

    async def _finalize_revoked_sessions(
        self, user_id: str, revoked_session_ids: list[str],
    ) -> None:
        redis = await get_redis_client()
        for revoked_session_id in revoked_session_ids:
            try:
                await self._fanout.fan_out_to_session(
                    revoked_session_id,
                    {"type": "session_revoked", "session_id": revoked_session_id},
                )
            except Exception as exc:
                logger.warning(
                    "세션 revoke fanout 실패: session_id={}, err={}",
                    revoked_session_id, exc,
                )
            finally:
                try:
                    await redis.delete(ws_route_key(revoked_session_id))
                except Exception as cleanup_exc:
                    logger.warning(
                        "revoke route cleanup 실패: session_id={}, err={}",
                        revoked_session_id, cleanup_exc,
                    )
            logger.info(
                "세션 한도 초과로 revoke: user_id={}, revoked_session_id={}",
                user_id, revoked_session_id,
            )

    async def heartbeat(self, session_id: str, user_id: str) -> bool:
        """live membership이면 TTL을 연장하고, revoke 상태면 route를 정리한다."""
        new_expires_ms = self._expires_ms()
        redis = await get_redis_client()
        script = lua_scripts.heartbeat_session
        if script is None:
            raise RuntimeError("heartbeat_session Lua script가 로드되지 않았습니다.")
        result = await script(
            keys=[
                sess_key(session_id),
                ws_route_key(session_id),
                sessions_key(user_id),
            ],
            args=[session_id, new_expires_ms, SESSION_TTL],
            client=redis,
        )
        return bool(result)

    async def update_token_jti(self, session_id: str, new_token_jti: str) -> None:
        """JWT refresh 시 token_jti 만 갱신. session_id 는 유지."""
        redis = await get_redis_client()
        await redis.hset(sess_key(session_id), "token_jti", new_token_jti)

    async def session_exists(self, session_id: str) -> bool:
        """매 op 진입부에서 호출 — False 면 revoke 된 상태 (TTL/DEL/강제 로그아웃 동일)."""
        redis = await get_redis_client()
        return bool(await redis.exists(sess_key(session_id)))

    async def get_user_id(self, session_id: str) -> str | None:
        """세션의 소유 user_id (없으면 None)."""
        redis = await get_redis_client()
        value = await redis.hget(sess_key(session_id), "user_id")
        return value if value else None

    async def terminate_session(self, session_id: str, user_id: str) -> None:
        """WS 종료 / 명시 로그아웃 시 Redis 상태 정리.

        호출 순서: FanoutService.unregister_ws → 본 메서드 → WS close.
        """
        redis = await get_redis_client()
        pipe = redis.pipeline(transaction=True)
        pipe.delete(sess_key(session_id))
        pipe.delete(ws_route_key(session_id))
        pipe.zrem(sessions_key(user_id), session_id)
        await pipe.execute()

    async def revoke_all_sessions(self, user_id: str) -> int:
        """유저의 모든 활성 세션 강제 종료 — 회원 탈퇴 등 외부 정책에서 호출.

        TTL 만료를 기다리지 않고 즉시 정리해 송수신 윈도우를 닫는다.
        오프라인 유저는 0 반환.
        """
        redis = await get_redis_client()
        session_ids = await redis.zrange(sessions_key(user_id), 0, -1)
        if not session_ids:
            return 0

        for sid in session_ids:
            await self._fanout.fan_out_to_session(
                sid, {"type": "session_revoked", "session_id": sid},
            )

        pipe = redis.pipeline(transaction=True)
        for sid in session_ids:
            pipe.delete(sess_key(sid), ws_route_key(sid))
        pipe.delete(sessions_key(user_id))
        await pipe.execute()

        logger.info(
            "전체 세션 revoke (회원 탈퇴 등): user_id={}, revoked_count={}",
            user_id, len(session_ids),
        )
        return len(session_ids)
