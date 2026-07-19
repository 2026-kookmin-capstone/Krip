"""애플리케이션 수명에 종속된 비동기 background task 관리."""
import asyncio
from collections.abc import Coroutine
from typing import Any

from app.core.logger import get_logger


logger = get_logger("background_tasks")


class BackgroundTaskSupervisor:
    def __init__(self, *, shutdown_grace_sec: float = 5.0) -> None:
        self._shutdown_grace_sec = shutdown_grace_sec
        self._tasks: set[asyncio.Task] = set()
        self._accepting = False

    @property
    def tasks(self) -> frozenset[asyncio.Task]:
        return frozenset(self._tasks)

    def start(self) -> None:
        if self._tasks:
            raise RuntimeError("background task가 남아 있어 supervisor를 시작할 수 없습니다.")
        self._accepting = True

    def spawn(
        self, coroutine: Coroutine[Any, Any, Any], *, name: str,
    ) -> asyncio.Task | None:
        if not self._accepting:
            coroutine.close()
            logger.warning("shutdown 중 background task 등록 거부: name={}", name)
            return None

        task = asyncio.create_task(coroutine, name=name)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    async def stop(self) -> None:
        self._accepting = False
        if not self._tasks:
            return

        tasks = set(self._tasks)
        cancelled = False
        try:
            _done, pending = await asyncio.wait(
                tasks, timeout=self._shutdown_grace_sec,
            )
        except asyncio.CancelledError:
            cancelled = True
            pending = tasks

        if pending:
            logger.info(
                "background task grace timeout: pending={}, cancel 시작",
                len(pending),
            )
            for task in pending:
                task.cancel()

        drain = asyncio.gather(*tasks, return_exceptions=True)
        while True:
            try:
                await asyncio.shield(drain)
                break
            except asyncio.CancelledError:
                if drain.cancelled():
                    raise
                cancelled = True
        if cancelled:
            raise asyncio.CancelledError

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        try:
            exception = task.exception()
        except asyncio.CancelledError:
            return
        if exception is not None:
            logger.error(
                "background task 예외: name={}, err={!r}",
                task.get_name(), exception,
            )


background_tasks = BackgroundTaskSupervisor()
