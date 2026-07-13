import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.tripmate.service.image_reference_mutex import TripmateImageReferenceMutex


class FakeEngine:
    def __init__(self, *, execute_error=None, commit_error=None):
        self.connections = []
        self.execute_error = execute_error
        self.commit_error = commit_error

    async def connect(self):
        connection = FakeConnection(self.execute_error, self.commit_error)
        self.connections.append(connection)
        return connection


class FakeConnection:
    def __init__(self, execute_error, commit_error):
        self.execute = AsyncMock(side_effect=execute_error)
        self.close = AsyncMock()
        self.transaction = MagicMock()
        self.transaction.commit = AsyncMock(side_effect=commit_error)
        self.transaction.rollback = AsyncMock()

    async def begin(self):
        return self.transaction


@pytest.mark.unit
async def test_same_task_reenters_without_second_database_lock():
    engine = FakeEngine()
    mutex = TripmateImageReferenceMutex(engine)

    async with mutex.hold("USER_a"):
        async with mutex.hold("USER_a"):
            pass

    assert len(engine.connections) == 1
    engine.connections[0].execute.assert_awaited_once()


@pytest.mark.unit
async def test_child_task_does_not_inherit_parent_reentrancy():
    engine = FakeEngine()
    mutex = TripmateImageReferenceMutex(engine)

    async with mutex.hold("USER_a"):
        await asyncio.create_task(_enter_once(mutex, "USER_a"))

    assert len(engine.connections) == 2
    assert all(connection.execute.await_count == 1 for connection in engine.connections)


@pytest.mark.unit
async def test_lock_acquisition_failure_is_fail_closed():
    engine = FakeEngine(execute_error=ConnectionError("database down"))

    with pytest.raises(ConnectionError, match="database down"):
        async with TripmateImageReferenceMutex(engine).hold("USER_a"):
            pass

    engine.connections[0].transaction.rollback.assert_awaited_once()
    engine.connections[0].close.assert_awaited_once()


@pytest.mark.unit
async def test_lock_release_failure_does_not_turn_completed_body_into_failure():
    engine = FakeEngine(commit_error=ConnectionError("database down"))
    completed = False

    async with TripmateImageReferenceMutex(engine).hold("USER_a"):
        completed = True

    assert completed is True
    engine.connections[0].close.assert_awaited_once()


async def _enter_once(mutex, user_id):
    async with mutex.hold(user_id):
        return None
