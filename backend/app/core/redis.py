import redis.asyncio as redis

from app.config.setting import settings


class RedisClient:
    """Redis 클라이언트 관리 클래스.

    - hot (DB 0) : 세션/시퀀스/unread/rate 등 핫 데이터
    - dedupe (DB 1) : dedupe 키 전용 격리 — 운영자의 `KEYS dedupe:*` 실수가
      세션/시퀀스에 영향주지 않도록 DB 번호 분리 (§3.3)
    """

    _client: "redis.Redis | None" = None
    _dedupe_client: "redis.Redis | None" = None

    # 캐시 TTL 상수
    DEFAULT_CACHE_TTL = 86400  # 24 hours in seconds
    SHORT_CACHE_TTL = 3600     # 1 hour in seconds
    MEDIUM_CACHE_TTL = 43200   # 12 hours in seconds

    @classmethod
    async def get_client(cls) -> redis.Redis:
        """hot Redis 클라이언트(DB 0)"""
        if cls._client is None:
            cls._client = redis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                encoding="utf-8"
            )
        return cls._client

    @classmethod
    async def get_dedupe_client(cls) -> redis.Redis:
        """dedupe 전용 Redis 클라이언트(DB 1)"""
        if cls._dedupe_client is None:
            cls._dedupe_client = redis.from_url(
                settings.REDIS_URL_DEDUPE,
                decode_responses=True,
                encoding="utf-8"
            )
        return cls._dedupe_client

    @classmethod
    async def close(cls):
        """Redis 연결 종료 (양쪽 DB)"""
        if cls._client:
            await cls._client.close()
            cls._client = None
        if cls._dedupe_client:
            await cls._dedupe_client.close()
            cls._dedupe_client = None


async def get_redis_client() -> redis.Redis:
    """hot Redis 클라이언트(DB 0) 반환"""
    return await RedisClient.get_client()


async def get_redis_dedupe_client() -> redis.Redis:
    """dedupe 전용 Redis 클라이언트(DB 1) 반환"""
    return await RedisClient.get_dedupe_client()


async def close_redis():
    """Redis 연결 종료"""
    await RedisClient.close()