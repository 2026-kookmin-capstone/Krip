import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar
from functools import wraps
from hashlib import blake2b
from inspect import signature
from typing import AsyncIterator, Callable

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.logger import get_logger


logger = get_logger("tripmate.image_reference_mutex")
_held_by_task: ContextVar[tuple[tuple[str, asyncio.Task], ...]] = ContextVar(
    "tripmate_image_reference_locks_by_task",
    default=(),
)


class TripmateImageReferenceMutex:
    """Cross-process per-user mutex backed by a dedicated PostgreSQL pool."""

    def __init__(self, engine: AsyncEngine):
        self.engine = engine

    @asynccontextmanager
    async def hold(self, user_id: str) -> AsyncIterator[None]:
        held = _held_by_task.get()
        owner = asyncio.current_task()
        if owner is not None and (user_id, owner) in held:
            yield
            return
        if owner is None:  # pragma: no cover - async context always has a task
            raise RuntimeError("이미지 참조 잠금 owner task가 없습니다.")

        connection = await self.engine.connect()
        try:
            transaction = await connection.begin()
            try:
                lock_key = int.from_bytes(
                    blake2b(user_id.encode(), digest_size=8).digest(),
                    byteorder="big",
                    signed=True,
                )
                await connection.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": lock_key},
                )
                token = _held_by_task.set((*held, (user_id, owner)))
                try:
                    yield
                finally:
                    _held_by_task.reset(token)
            except BaseException:
                await self._finish(transaction.rollback, user_id)
                raise
            else:
                await self._finish(transaction.commit, user_id)
        finally:
            await self._finish(connection.close, user_id)

    @staticmethod
    async def _finish(action: Callable, user_id: str) -> None:
        try:
            await action()
        except Exception as error:
            logger.error("이미지 참조 잠금 정리 실패: user_id={}, err={}", user_id, error)


class NoopTripmateImageReferenceMutex:
    @asynccontextmanager
    async def hold(self, _user_id: str) -> AsyncIterator[None]:
        yield


def image_reference_locked(func: Callable) -> Callable:
    func_signature = signature(func)

    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        bound = func_signature.bind(self, *args, **kwargs)
        user_id = bound.arguments["user_id"]
        async with self.image_mutex.hold(user_id):
            return await func(self, *args, **kwargs)

    return wrapper
