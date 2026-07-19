from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.friend.repository.user_block import UserBlockRepository


@pytest.mark.unit
async def test_acquire_pair_lock_uses_canonical_transaction_lock():
    session = SimpleNamespace(execute=AsyncMock())
    repository = UserBlockRepository(cast(AsyncSession, session))

    await repository.acquire_pair_lock("USER_b", "USER_a")

    statement, params = session.execute.await_args.args
    assert "pg_advisory_xact_lock" in str(statement)
    assert params == {"key": "USER_a:USER_b"}


@pytest.mark.unit
async def test_acquire_pair_lock_shared_uses_shared_transaction_lock():
    session = SimpleNamespace(execute=AsyncMock())
    repository = UserBlockRepository(cast(AsyncSession, session))

    await repository.acquire_pair_lock_shared("USER_b", "USER_a")

    statement, params = session.execute.await_args.args
    assert "pg_advisory_xact_lock_shared" in str(statement)
    assert params == {"key": "USER_a:USER_b"}
