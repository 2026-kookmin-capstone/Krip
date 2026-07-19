"""친구 상태 전이의 행 잠금(SELECT ... FOR UPDATE) 을 실 DB(PostgreSQL) 로 검증.

regression: accept/reject/cancel/remove 는 find_by_id → 상태검사 → update/delete 사이가
원자적이지 않아, 동시 실행 시 lost update 로 방금 성립한 친구관계가 조용히 삭제되거나
StaleDataError(500) 가 발생했다. `find_by_id(for_update=True)` 가 실제로 행을 잠가
검사~쓰기 구간을 직렬화하는지 확인한다.
"""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.domain.friend.model.friendship import Friendship, FriendshipStatus
from app.domain.friend.repository.friendship import FriendshipRepository
from app.domain.friend.service.friendship import FriendshipService


pytestmark = pytest.mark.integration


async def _seed_pending(seed_users, session_factory) -> tuple[str, str, str]:
    a, b, _ = await seed_users(3)
    async with session_factory() as s:
        s.add(Friendship(requester_id=a, addressee_id=b, status=FriendshipStatus.PENDING))
        await s.commit()
    async with session_factory() as s:
        row = (
            await s.execute(
                select(Friendship).where(
                    Friendship.requester_id == a,
                    Friendship.addressee_id == b,
                )
            )
        ).scalar_one()
        return a, b, row.friendship_id


class TestStateTransitionRowLock:
    async def test_for_update_locks_row_against_concurrent_transaction(
        self, seed_users, session_factory,
    ):
        """for_update 로 잠근 행은 다른 트랜잭션의 잠금 시도를 막는다.

        s1 이 프로덕션 경로(find_by_id(for_update=True))로 행을 잠근 상태에서, s2 가 같은
        행을 NOWAIT 로 잠그려 하면 즉시 실패한다 = s1 이 실제 DB 잠금을 보유했다는 증거.
        """
        _, _, fid = await _seed_pending(seed_users, session_factory)

        async with session_factory() as s1:
            locked = await FriendshipRepository(s1).find_by_id(fid, for_update=True)
            assert locked is not None  # 잠금 획득 + 트랜잭션 유지 중

            async with session_factory() as s2:
                probe = (
                    select(Friendship)
                    .where(Friendship.friendship_id == fid)
                    .with_for_update(nowait=True)
                )
                with pytest.raises(DBAPIError):
                    await s2.execute(probe)

    async def test_accept_then_cancel_guard_holds(
        self, seed_users, session_factory, uow,
    ):
        """수락 확정 후 취소 시도는 상태 검사에 걸려 ACCEPTED 를 삭제하지 않는다.

        잠금으로 직렬화된 뒤 두 번째 전이가 최신 상태를 다시 읽으므로, cancel 은
        '대기 중인 요청만 취소' 에서 멈추고 friendship 은 ACCEPTED 로 보존된다.
        """
        a, b, fid = await _seed_pending(seed_users, session_factory)
        service = FriendshipService(uow=uow)

        await service.accept_request(friendship_id=fid, user_id=b)

        with pytest.raises(ValueError, match="대기 중"):
            await service.cancel_request(friendship_id=fid, user_id=a)

        async with session_factory() as s:
            row = await s.get(Friendship, fid)
            assert row is not None, "ACCEPTED 친구관계가 취소로 삭제되면 안 됨"
            assert row.status == FriendshipStatus.ACCEPTED
