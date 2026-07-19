"""database.session — @transactional 전파 가드와 Mongo 인덱스 부팅 내성."""
import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo.errors import DuplicateKeyError

from app.database import session as session_module
from app.database.session import transactional


pytestmark = pytest.mark.unit


class FakeUnitOfWork:
    def __init__(self):
        self.session = MagicMock(name="tx-session")

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _Service:
    def __init__(self):
        self.uow = FakeUnitOfWork()
        self.joined_sessions = []

    @transactional
    async def outer_sequential(self):
        await self.inner()
        await self.inner()

    @transactional
    async def outer_gather(self):
        await asyncio.gather(self.inner(), self.inner())

    @transactional
    async def inner(self):
        self.joined_sessions.append(self._session)


class TestTransactionalPropagation:
    async def test_nested_same_task_joins_parent_session(self):
        service = _Service()
        await service.outer_sequential()

        assert len(service.joined_sessions) == 2
        assert service.joined_sessions[0] is service.joined_sessions[1]
        assert service.joined_sessions[0] is service.uow.session

    async def test_gathered_transactional_calls_fail_loudly(self):
        """상속된 세션에 다른 task 가 join 하면 asyncpg 오류로 터지기 전에 명시적으로 거부."""
        service = _Service()
        with pytest.raises(RuntimeError, match="task 간 공유"):
            await service.outer_gather()

    async def test_top_level_reusable_after_previous_transaction(self):
        service = _Service()
        await service.inner()
        await service.inner()

        assert len(service.joined_sessions) == 2


def _index_collection(create_index_side_effect):
    async def _empty_cursor(*_args, **_kwargs):
        if False:
            yield

    collection = MagicMock(name="collection")
    collection.name = "friend_search_history"
    collection.index_information = AsyncMock(return_value={})
    collection.aggregate = MagicMock(side_effect=_empty_cursor)
    collection.delete_many = AsyncMock()
    collection.create_index = AsyncMock(side_effect=create_index_side_effect)
    return collection


def _indexed_collection():
    collection = MagicMock(name="collection-indexed")
    collection.index_information = AsyncMock(
        return_value={session_module._SEARCH_HISTORY_UNIQUE_INDEX: {}},
    )
    return collection


@pytest.fixture
def patch_models(monkeypatch):
    def _patch(target_collection):
        models = (
            session_module.FriendSearchHistory,
            session_module.TourSearchHistory,
            session_module.TripmateSearchHistory,
        )
        monkeypatch.setattr(
            models[0], "get_motor_collection", lambda: target_collection,
        )
        for model in models[1:]:
            monkeypatch.setattr(
                model, "get_motor_collection", _indexed_collection,
            )

    return _patch


class TestSearchHistoryIndexBootstrap:
    async def test_duplicate_during_creation_retries_dedup(self, patch_models):
        """dedup 과 create_index 사이 끼어든 중복 → 재시도로 인덱스 생성 성공."""
        collection = _index_collection([DuplicateKeyError("dup"), None])
        patch_models(collection)

        await session_module._ensure_search_history_unique_indexes()

        assert collection.create_index.await_count == 2

    async def test_retry_exhaustion_boots_without_index(self, patch_models):
        """재시도 소진 시 crash-loop 대신 인덱스 없이 부팅 — 다음 재시작이 재시도."""
        collection = _index_collection(DuplicateKeyError("dup"))
        patch_models(collection)

        await session_module._ensure_search_history_unique_indexes()

        assert (
            collection.create_index.await_count
            == session_module._SEARCH_HISTORY_INDEX_ATTEMPTS
        )
