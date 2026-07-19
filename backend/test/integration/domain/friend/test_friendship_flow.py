"""FriendshipService 통합 테스트.

실제 PostgreSQL, 실제 Repository 를 사용해 서비스 전체 플로우를 검증한다.
"""

import pytest
from sqlalchemy import select

from app.domain.friend.model.friendship import Friendship, FriendshipStatus
from app.domain.friend.service.friendship import FriendshipService


pytestmark = pytest.mark.integration


class TestSendRequestFlow:
    async def test_creates_pending_row(self, uow, seed_users, session_factory):
        a, b, _ = await seed_users(3)
        service = FriendshipService(uow=uow)

        result = await service.send_request(requester_id=a, addressee_id=b)

        assert result.status == FriendshipStatus.PENDING
        assert result.peer.user_id == b
        assert result.is_requester is True

        async with session_factory() as s:
            row = (await s.execute(select(Friendship))).scalar_one()
            assert row.requester_id == a
            assert row.addressee_id == b
            assert row.status == FriendshipStatus.PENDING

    async def test_self_request_rejected(self, uow, seed_users):
        (a,) = await seed_users(1)
        service = FriendshipService(uow=uow)

        with pytest.raises(ValueError, match="자기 자신"):
            await service.send_request(requester_id=a, addressee_id=a)

    async def test_unknown_addressee_rejected(self, uow, seed_users):
        (a,) = await seed_users(1)
        service = FriendshipService(uow=uow)

        with pytest.raises(ValueError, match="존재하지 않는 유저"):
            await service.send_request(requester_id=a, addressee_id="USER_ghost")

    async def test_duplicate_pending_by_me_rejected(self, uow, seed_users):
        a, b, _ = await seed_users(3)
        service = FriendshipService(uow=uow)

        await service.send_request(requester_id=a, addressee_id=b)
        with pytest.raises(ValueError, match="이미 친구 요청을 보낸"):
            await service.send_request(requester_id=a, addressee_id=b)

    async def test_reverse_pending_hints_accept(self, uow, seed_users):
        a, b, _ = await seed_users(3)
        service = FriendshipService(uow=uow)

        await service.send_request(requester_id=a, addressee_id=b)

        with pytest.raises(ValueError, match="수락해주세요"):
            await service.send_request(requester_id=b, addressee_id=a)

    async def test_rejected_can_be_reissued_via_upsert(self, uow, seed_users, session_factory):
        a, b, _ = await seed_users(3)
        service = FriendshipService(uow=uow)

        first = await service.send_request(requester_id=a, addressee_id=b)
        await service.reject_request(friendship_id=first.friendship_id, user_id=b)

        reissued = await service.send_request(requester_id=a, addressee_id=b)

        assert reissued.friendship_id == first.friendship_id
        assert reissued.status == FriendshipStatus.PENDING

        async with session_factory() as s:
            rows = (await s.execute(select(Friendship))).scalars().all()
            assert len(rows) == 1
            assert rows[0].status == FriendshipStatus.PENDING

    async def test_rejected_swap_direction_on_reverse_reissue(self, uow, seed_users, session_factory):
        """A→B 거절 이력이 있는 상태에서 이번엔 B→A 요청 → 방향이 swap 되어야 한다."""
        a, b, _ = await seed_users(3)
        service = FriendshipService(uow=uow)

        first = await service.send_request(requester_id=a, addressee_id=b)
        await service.reject_request(friendship_id=first.friendship_id, user_id=b)

        reissued = await service.send_request(requester_id=b, addressee_id=a)
        assert reissued.status == FriendshipStatus.PENDING

        async with session_factory() as s:
            row = (await s.execute(select(Friendship))).scalar_one()
            assert row.requester_id == b
            assert row.addressee_id == a


class TestAcceptFlow:
    async def test_status_becomes_accepted(self, uow, seed_users, session_factory):
        a, b, _ = await seed_users(3)
        service = FriendshipService(uow=uow)

        created = await service.send_request(requester_id=a, addressee_id=b)
        await service.accept_request(friendship_id=created.friendship_id, user_id=b)

        async with session_factory() as s:
            row = (await s.execute(select(Friendship))).scalar_one()
            assert row.status == FriendshipStatus.ACCEPTED

    async def test_wrong_user_forbidden(self, uow, seed_users):
        a, b, c = await seed_users(3)
        service = FriendshipService(uow=uow)

        created = await service.send_request(requester_id=a, addressee_id=b)
        with pytest.raises(PermissionError, match="수락 권한"):
            await service.accept_request(friendship_id=created.friendship_id, user_id=c)


class TestRejectFlow:
    async def test_status_becomes_rejected(self, uow, seed_users, session_factory):
        a, b, _ = await seed_users(3)
        service = FriendshipService(uow=uow)

        created = await service.send_request(requester_id=a, addressee_id=b)
        await service.reject_request(friendship_id=created.friendship_id, user_id=b)

        async with session_factory() as s:
            row = (await s.execute(select(Friendship))).scalar_one()
            assert row.status == FriendshipStatus.REJECTED


class TestCancelFlow:
    async def test_deletes_pending(self, uow, seed_users, session_factory):
        a, b, _ = await seed_users(3)
        service = FriendshipService(uow=uow)

        created = await service.send_request(requester_id=a, addressee_id=b)
        await service.cancel_request(friendship_id=created.friendship_id, user_id=a)

        async with session_factory() as s:
            rows = (await s.execute(select(Friendship))).scalars().all()
            assert rows == []


class TestRemoveFriendFlow:
    async def test_deletes_accepted(self, uow, seed_users, session_factory):
        a, b, _ = await seed_users(3)
        service = FriendshipService(uow=uow)

        created = await service.send_request(requester_id=a, addressee_id=b)
        await service.accept_request(friendship_id=created.friendship_id, user_id=b)
        await service.remove_friend(friendship_id=created.friendship_id, user_id=a)

        async with session_factory() as s:
            rows = (await s.execute(select(Friendship))).scalars().all()
            assert rows == []

    async def test_third_party_forbidden(self, uow, seed_users):
        a, b, c = await seed_users(3)
        service = FriendshipService(uow=uow)

        created = await service.send_request(requester_id=a, addressee_id=b)
        await service.accept_request(friendship_id=created.friendship_id, user_id=b)

        with pytest.raises(PermissionError, match="삭제 권한"):
            await service.remove_friend(friendship_id=created.friendship_id, user_id=c)


class TestListFlow:
    async def test_received_and_sent_partition(self, uow, seed_users):
        a, b, c = await seed_users(3)
        service = FriendshipService(uow=uow)

        await service.send_request(requester_id=a, addressee_id=b)
        await service.send_request(requester_id=c, addressee_id=a)

        received = await service.get_received_requests(user_id=a)
        sent = await service.get_sent_requests(user_id=a)

        assert len(received.items) == 1
        assert received.items[0].peer.user_id == c
        assert received.items[0].is_requester is False

        assert len(sent.items) == 1
        assert sent.items[0].peer.user_id == b
        assert sent.items[0].is_requester is True

    async def test_friends_returns_only_accepted(self, uow, seed_users):
        a, b, c = await seed_users(3)
        service = FriendshipService(uow=uow)

        created_ab = await service.send_request(requester_id=a, addressee_id=b)
        await service.accept_request(friendship_id=created_ab.friendship_id, user_id=b)

        await service.send_request(requester_id=c, addressee_id=a)

        friends = await service.get_friends(user_id=a)
        assert len(friends.items) == 1
        assert friends.items[0].peer.user_id == b
        assert friends.items[0].status == FriendshipStatus.ACCEPTED


class TestInactiveCounterpartHidden:
    """탈퇴 유예(INACTIVE) 상대는 목록·카운트·초대 후보에서 일관되게 제외된다."""

    async def _accept_friends(self, uow, a: str, b: str) -> None:
        service = FriendshipService(uow=uow)
        sent = await service.send_request(requester_id=a, addressee_id=b)
        await service.accept_request(user_id=b, friendship_id=sent.friendship_id)

    async def test_count_matches_filtered_list_after_withdrawal(
        self, uow, seed_users, session_factory,
    ):
        from sqlalchemy import update

        from app.domain.auth.model.user import User, UserStatus
        from app.domain.friend.repository.friendship import FriendshipRepository

        a, b, c = await seed_users(3)
        await self._accept_friends(uow, a, b)
        await self._accept_friends(uow, a, c)

        async with session_factory() as s:
            await s.execute(
                update(User).where(User.user_id == b).values(status=UserStatus.INACTIVE)
            )
            await s.commit()

        async with session_factory() as s:
            repo = FriendshipRepository(s)
            friends = await repo.find_friends(a)
            count = await repo.count_accepted_for(a)
            friend_ids = await repo.find_accepted_friend_ids(a)

        listed_peers = {
            f.addressee_id if f.requester_id == a else f.requester_id for f in friends
        }
        assert listed_peers == {c}
        assert count == 1
        assert friend_ids == {c}
