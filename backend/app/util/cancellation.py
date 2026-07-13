import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar


T = TypeVar("T")


async def drain_on_cancellation(awaitable: Coroutine[Any, Any, T]) -> tuple[T, bool]:
    """수락된 async 작업을 끝까지 drain하고 호출자 cancellation 여부를 함께 반환한다."""
    task = asyncio.create_task(awaitable)
    cancelled = False
    while True:
        try:
            return await asyncio.shield(task), cancelled
        except asyncio.CancelledError:
            if task.cancelled():
                raise
            cancelled = True
