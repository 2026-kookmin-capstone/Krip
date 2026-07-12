import redis.asyncio as redis

from app.config.setting import settings
from app.core.instrumentation import instrument_redis_client


# 무한 대기를 막되 Redis Lua 5초 상한과 PubSub 1초 polling보다 짧게 잡지 않는다.
# BLPOP/BRPOP/XREAD 등 blocking 명령은 socket_timeout(5s)에 먼저 끊기므로, block
# timeout을 5s 미만으로 주거나 socket_timeout=None 인 별도 client를 써야 한다.
_REDIS_SOCKET_TIMEOUT_SEC = 5.0
_REDIS_SOCKET_CONNECT_TIMEOUT_SEC = 3.0


class RedisClient:
    """Redis 클라이언트 관리 클래스.

    - hot (DB 0) : 세션/시퀀스/unread/rate 등 핫 데이터
    - dedupe (DB 1) : dedupe 키 전용 격리 — 운영자의 `KEYS dedupe:*` 실수가
      세션/시퀀스에 영향주지 않도록 DB 번호 분리 (§3.3)
    """

    _client: "redis.Redis | None" = None
    _dedupe_client: "redis.Redis | None" = None

    DEFAULT_CACHE_TTL = 86400
    SHORT_CACHE_TTL = 3600
    MEDIUM_CACHE_TTL = 43200

    @classmethod
    async def get_client(cls) -> redis.Redis:
        """hot Redis 클라이언트(DB 0)"""
        if cls._client is None:
            cls._client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                encoding="utf-8",
                socket_timeout=_REDIS_SOCKET_TIMEOUT_SEC,
                socket_connect_timeout=_REDIS_SOCKET_CONNECT_TIMEOUT_SEC,
            )
            instrument_redis_client(cls._client, db="hot")
        return cls._client

    @classmethod
    async def get_dedupe_client(cls) -> redis.Redis:
        """dedupe 전용 Redis 클라이언트(DB 1)"""
        if cls._dedupe_client is None:
            cls._dedupe_client = redis.from_url(
                settings.REDIS_URL_DEDUPE,
                decode_responses=True,
                encoding="utf-8",
                socket_timeout=_REDIS_SOCKET_TIMEOUT_SEC,
                socket_connect_timeout=_REDIS_SOCKET_CONNECT_TIMEOUT_SEC,
            )
            instrument_redis_client(cls._dedupe_client, db="dedupe")
        return cls._dedupe_client

    @classmethod
    async def close(cls):
        """Redis 연결 종료 (양쪽 DB)"""
        clients = (cls._client, cls._dedupe_client)
        cls._client = None
        cls._dedupe_client = None

        first_error: BaseException | None = None
        for client in clients:
            if client is None:
                continue
            try:
                await client.close()
            except BaseException as error:
                if first_error is None:
                    first_error = error

        if first_error is not None:
            raise first_error


async def get_redis_client() -> redis.Redis:
    """hot Redis 클라이언트(DB 0) 반환"""
    return await RedisClient.get_client()


async def get_redis_dedupe_client() -> redis.Redis:
    """dedupe 전용 Redis 클라이언트(DB 1) 반환"""
    return await RedisClient.get_dedupe_client()


async def close_redis():
    """Redis 연결 종료"""
    await RedisClient.close()