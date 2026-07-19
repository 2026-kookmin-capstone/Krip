import asyncio
import contextvars
from collections.abc import Awaitable, Callable, Coroutine
from functools import partial
from typing import Any, ParamSpec, TypeVar


P = ParamSpec("P")
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


async def drain_thread_on_cancellation(
    func: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs,
) -> tuple[T, bool]:
    """executor 작업을 Task cancellation과 분리하고 실제 thread 종료까지 기다린다.

    `asyncio.to_thread`와 동일하게 contextvars를 복사해 thread 내 로그가
    request_id 상관관계를 유지한다.
    """
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    future = loop.run_in_executor(None, partial(ctx.run, func, *args, **kwargs))
    cancelled = False
    while True:
        try:
            return await asyncio.shield(future), cancelled
        except asyncio.CancelledError:
            cancelled = True
            if future.done():
                return future.result(), cancelled


async def gather_on_cancellation(
    *awaitables: Awaitable[Any],
) -> tuple[list[Any], bool]:
    """자식이 직접 취소돼도 모든 결과를 수집한 뒤 호출자 cancellation을 보고한다."""
    tasks = [asyncio.ensure_future(awaitable) for awaitable in awaitables]
    gathered = asyncio.gather(*tasks, return_exceptions=True)
    cancelled = False
    while True:
        try:
            return list(await asyncio.shield(gathered)), cancelled
        except asyncio.CancelledError:
            cancelled = True
            if gathered.done() and not gathered.cancelled():
                return list(gathered.result()), cancelled
