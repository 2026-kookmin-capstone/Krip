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


@pytest.mark.unit
async def test_pushable_lookup_locks_accounts_before_memberships():
    account_result = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: ["U_A"]),
    )
    member_result = SimpleNamespace(
        all=lambda: [SimpleNamespace(user_id="U_A", joined_at=None)],
    )
    session = SimpleNamespace(
        execute=AsyncMock(side_effect=[account_result, member_result]),
    )
    repository = ChatRoomMemberRepository(cast(AsyncSession, session))

    result = await repository.find_pushable_user_ids_in_room("CR_1", ["U_A"])

    assert result == {"U_A"}
    account_stmt, member_stmt = [call.args[0] for call in session.execute.await_args_list]
    account_sql = str(account_stmt.compile(dialect=postgresql.dialect()))
    member_sql = str(member_stmt.compile(dialect=postgresql.dialect()))
    assert "FROM users" in account_sql
    assert "chat_room_member" not in account_sql
    assert "FROM chat_room_member" in member_sql
    assert "JOIN users" not in member_sql
    assert "FOR SHARE" in account_sql
    assert "FOR SHARE" in member_sql
