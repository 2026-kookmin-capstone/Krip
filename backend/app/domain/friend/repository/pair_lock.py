from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def acquire_pair_lock(
    session: AsyncSession,
    user_a_id: str,
    user_b_id: str,
    *,
    shared: bool = False,
) -> None:
    """방향과 무관한 두 사용자 트랜잭션 advisory lock을 획득한다."""
    least, greatest = sorted((user_a_id, user_b_id))
    statement = (
        text("SELECT pg_advisory_xact_lock_shared(hashtext(:key))")
        if shared
        else text("SELECT pg_advisory_xact_lock(hashtext(:key))")
    )
    await session.execute(
        statement,
        {"key": f"{least}:{greatest}"},
    )
