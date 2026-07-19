"""UserBlockService 통합 테스트 + friendship 과의 크로스도메인 상호작용."""

import pytest
from sqlalchemy import select

from app.domain.friend.model.friendship import Friendship
from app.domain.friend.model.user_block import UserBlock
from app.domain.friend.service.friendship import FriendshipService
from app.domain.friend.service.user_block import UserBlockService


pytestmark = pytest.mark.integration


class TestBlockFlow:
    async def test_creates_block_row(self, uow, seed_users, session_factory):
        a, b, _ = await seed_users(3)
        service = UserBlockService(uow=uow)

        result = await service.block_user(user_id=a, target_user_id=b)

        assert result.blocked.user_id == b

        async with session_factory() as s:
            row = (await s.execute(select(UserBlock))).scalar_one()
            assert row.blocker_id == a
            assert row.blocked_id == b

    async def test_self_block_rejected(self, uow, seed_users):
        (a,) = await seed_users(1)
        service = UserBlockService(uow=uow)

        with pytest.raises(ValueError, match="자기 자신"):
            await service.block_user(user_id=a, target_user_id=a)

    async def test_duplicate_block_rejected(self, uow, seed_users):
        a, b, _ = await seed_users(3)
        service = UserBlockService(uow=uow)

        await service.block_user(user_id=a, target_user_id=b)
        with pytest.raises(ValueError, match="이미 차단"):
            await service.block_user(user_id=a, target_user_id=b)

    async def test_mutual_block_allowed_as_separate_rows(self, uow, seed_users, session_factory):
        """A↔B 상호 차단은 방향별 별도 row 2건으로 공존."""
        a, b, _ = await seed_users(3)
        service = UserBlockService(uow=uow)

        await service.block_user(user_id=a, target_user_id=b)
        await service.block_user(user_id=b, target_user_id=a)

        async with session_factory() as s:
            rows = (await s.execute(select(UserBlock))).scalars().all()
            assert len(rows) == 2
            pairs = {(r.blocker_id, r.blocked_id) for r in rows}
            assert pairs == {(a, b), (b, a)}


class TestUnblockFlow:
    async def test_deletes_block_row(self, uow, seed_users, session_factory):
        a, b, _ = await seed_users(3)
        service = UserBlockService(uow=uow)

        await service.block_user(user_id=a, target_user_id=b)
        await service.unblock_user(user_id=a, target_user_id=b)

        async with session_factory() as s:
            rows = (await s.execute(select(UserBlock))).scalars().all()
            assert rows == []

    async def test_unblock_when_not_blocked(self, uow, seed_users):
        a, b, _ = await seed_users(3)
        service = UserBlockService(uow=uow)

        with pytest.raises(ValueError, match="차단 상태가 아닙니다"):
            await service.unblock_user(user_id=a, target_user_id=b)


class TestListFlow:
    async def test_lists_only_my_blocks(self, uow, seed_users):
        a, b, c = await seed_users(3)
        service = UserBlockService(uow=uow)

        await service.block_user(user_id=a, target_user_id=b)
        await service.block_user(user_id=c, target_user_id=a)

        result = await service.get_blocked_users(user_id=a)

        assert len(result.items) == 1
        assert result.items[0].blocked.user_id == b


class TestBlockFriendshipInteraction:
    async def test_blocking_removes_existing_friendship(self, uow, seed_users, session_factory):
        a, b, _ = await seed_users(3)
        friendship_service = FriendshipService(uow=uow)
        block_service = UserBlockService(uow=uow)

        created = await friendship_service.send_request(requester_id=a, addressee_id=b)
        await friendship_service.accept_request(friendship_id=created.friendship_id, user_id=b)

        await block_service.block_user(user_id=a, target_user_id=b)

        async with session_factory() as s:
            friendships = (await s.execute(select(Friendship))).scalars().all()
            blocks = (await s.execute(select(UserBlock))).scalars().all()
        assert friendships == []
        assert len(blocks) == 1

    async def test_blocking_removes_pending_request_from_target(self, uow, seed_users, session_factory):
        """상대가 보낸 PENDING 요청이 있어도 내가 차단하면 같이 정리된다."""
        a, b, _ = await seed_users(3)
        friendship_service = FriendshipService(uow=uow)
        block_service = UserBlockService(uow=uow)

        await friendship_service.send_request(requester_id=b, addressee_id=a)
        await block_service.block_user(user_id=a, target_user_id=b)

        async with session_factory() as s:
            friendships = (await s.execute(select(Friendship))).scalars().all()
        assert friendships == []

    async def test_send_request_rejected_when_i_blocked_target(self, uow, seed_users):
        a, b, _ = await seed_users(3)
        friendship_service = FriendshipService(uow=uow)
        block_service = UserBlockService(uow=uow)

        await block_service.block_user(user_id=a, target_user_id=b)

        with pytest.raises(ValueError, match="차단한 유저"):
            await friendship_service.send_request(requester_id=a, addressee_id=b)

    async def test_send_request_rejected_when_target_blocked_me(self, uow, seed_users):
        a, b, _ = await seed_users(3)
        friendship_service = FriendshipService(uow=uow)
        block_service = UserBlockService(uow=uow)

        await block_service.block_user(user_id=b, target_user_id=a)

        with pytest.raises(ValueError, match="요청을 보낼 수 없습니다"):
            await friendship_service.send_request(requester_id=a, addressee_id=b)

    async def test_unblock_does_not_restore_friendship(self, uow, seed_users, session_factory):
        a, b, _ = await seed_users(3)
        friendship_service = FriendshipService(uow=uow)
        block_service = UserBlockService(uow=uow)

        created = await friendship_service.send_request(requester_id=a, addressee_id=b)
        await friendship_service.accept_request(friendship_id=created.friendship_id, user_id=b)

        await block_service.block_user(user_id=a, target_user_id=b)
        await block_service.unblock_user(user_id=a, target_user_id=b)

        async with session_factory() as s:
            friendships = (await s.execute(select(Friendship))).scalars().all()
        assert friendships == []
