from unittest.mock import AsyncMock

import pytest

from app.core.redis import RedisClient


pytestmark = pytest.mark.unit


async def test_close_attempts_both_clients_and_preserves_first_error():
    hot = AsyncMock()
    hot.close.side_effect = RuntimeError("hot close failed")
    dedupe = AsyncMock()
    RedisClient._client = hot
    RedisClient._dedupe_client = dedupe

    with pytest.raises(RuntimeError, match="hot close failed"):
        await RedisClient.close()

    hot.close.assert_awaited_once()
    dedupe.close.assert_awaited_once()
    assert RedisClient._client is None
    assert RedisClient._dedupe_client is None
