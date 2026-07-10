from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.chat.repository.chat_member import ChatRoomMemberRepository


@pytest.mark.unit
async def test_is_active_member_for_share_locks_active_membership():
    session = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(scalar_one_or_none=lambda: "U_A"),
        ),
    )
    repository = ChatRoomMemberRepository(cast(AsyncSession, session))

    result = await repository.is_active_member_for_share("CR_1", "U_A")

    assert result is True
    statement = session.execute.await_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect()))
    assert "FOR SHARE" in sql
