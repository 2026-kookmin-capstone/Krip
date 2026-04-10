from typing import Optional
import json
from functools import lru_cache

from app.core.redis import get_redis_client, RedisClient
from app.core.logger import get_logger


logger = get_logger("core.cache.category")


class RedisCacheManager:
    """Redis에 캐싱하는 관리 클래스"""

    def __init__(self):
        self._redis_client = None


    async def _ensure_redis_client(self):
        if not self._redis_client:
            self._redis_client = await get_redis_client()


    async def get_category(self, REDIS_KEY: str) -> Optional[dict]:
        try:
            await self._ensure_redis_client()
            data = await self._redis_client.get(REDIS_KEY)
            if data:
                logger.debug("카테고리 캐시 히트")
                return json.loads(data)
            return None
        except Exception as e:
            logger.error("카테고리 캐시 조회 실패: %s", e)
            return None


    async def set_category(self, data: dict, REDIS_KEY: str) -> None:
        try:
            await self._ensure_redis_client()
            await self._redis_client.set(
                REDIS_KEY,
                json.dumps(data, ensure_ascii=False),
                ex=RedisClient.SHORT_CACHE_TTL
            )
            logger.debug("카테고리 캐시 저장 완료")
        except Exception as e:
            logger.error("카테고리 캐시 저장 실패: %s", e)


    async def invalidate(self, REDIS_KEY: str) -> None:
        try:
            await self._ensure_redis_client()
            await self._redis_client.delete(REDIS_KEY)
            logger.info("카테고리 캐시 무효화 완료")
        except Exception as e:
            logger.error("카테고리 캐시 무효화 실패: %s", e)


    async def exists(self, key: str) -> bool:
        """키 존재 여부 확인"""
        try:
            await self._ensure_redis_client()
            return await self._redis_client.exists(key) > 0
        except Exception as e:
            logger.error("캐시 존재 여부 확인 실패: %s", e)
            return False


    async def set_flag(self, key: str, ttl: int) -> None:
        """단순 플래그 값 캐싱"""
        try:
            await self._ensure_redis_client()
            await self._redis_client.set(key, "1", ex=ttl)
            logger.debug("플래그 캐시 저장: %s", key)
        except Exception as e:
            logger.error("플래그 캐시 저장 실패: %s", e)


@lru_cache(maxsize=1)
def get_redis_cache_manager() -> RedisCacheManager:
    return RedisCacheManager()
