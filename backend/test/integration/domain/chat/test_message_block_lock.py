import pytest
from sqlalchemy import text

from app.domain.friend.repository.user_block import UserBlockRepository


pytestmark = pytest.mark.integration


async def test_direct_send_pair_lock_conflicts_with_block_pair_lock(session_factory):
    async with session_factory() as send_session:
        await UserBlockRepository(send_session).acquire_pair_lock_shared("USER_b", "USER_a")

        async with session_factory() as parallel_send_session:
            result = await parallel_send_session.execute(
                text("SELECT pg_try_advisory_xact_lock_shared(hashtext(:key))"),
                {"key": "USER_a:USER_b"},
            )
            assert result.scalar_one() is True

        async with session_factory() as block_session:
            result = await block_session.execute(
                text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
                {"key": "USER_a:USER_b"},
            )
            assert result.scalar_one() is False

        await send_session.commit()

    async with session_factory() as next_session:
        result = await next_session.execute(
            text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"),
            {"key": "USER_a:USER_b"},
        )
        assert result.scalar_one() is True
