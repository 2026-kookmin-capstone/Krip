"""FriendSearchService 통합 테스트 — 실 PostgreSQL 로 검색 / 필터 / 페이지네이션 검증."""

import pytest
from sqlalchemy import delete, update

from app.domain.auth.model.user import User, UserStatus
from app.domain.auth.model.user_detail_inform import UserDetailInform
from app.domain.auth.model.user_travel_style import TravelStyle, UserTravelStyle
from app.domain.friend.model.friendship import FriendshipStatus
from app.domain.friend.repository.search import PAGE_SIZE
from app.domain.friend.service.friendship import FriendshipService
from app.domain.friend.service.search import FriendSearchService
from app.domain.friend.service.user_block import UserBlockService


pytestmark = pytest.mark.integration


class TestKeywordValidation:
    async def test_raises_value_error_on_empty_keyword(self, uow, seed_users):
        (a,) = await seed_users(1)
        service = FriendSearchService(uow=uow)

        with pytest.raises(ValueError, match="검색어"):
            await service.search(viewer_id=a, keyword="")

    async def test_raises_value_error_on_whitespace_only(self, uow, seed_users):
        (a,) = await seed_users(1)
        service = FriendSearchService(uow=uow)

        with pytest.raises(ValueError, match="검색어"):
            await service.search(viewer_id=a, keyword="   ")

    async def test_strips_whitespace_in_keyword(self, uow, seed_users):
        a, b, _ = await seed_users(3)
        service = FriendSearchService(uow=uow)

        result = await service.search(viewer_id=a, keyword="  user1  ")

        item_ids = {item.user_id for item in result.items}
        assert b in item_ids


class TestExclusions:
    async def test_excludes_self(self, uow, seed_users):
        a, b, c = await seed_users(3)
        service = FriendSearchService(uow=uow)

        result = await service.search(viewer_id=a, keyword="user")

        item_ids = {item.user_id for item in result.items}
        assert a not in item_ids
        assert b in item_ids
        assert c in item_ids

    async def test_excludes_inactive_users(self, uow, seed_users, session_factory):
        a, b, c = await seed_users(3)

        async with session_factory() as s:
            await s.execute(
                update(User).where(User.user_id == b).values(status=UserStatus.INACTIVE)
            )
            await s.commit()

        service = FriendSearchService(uow=uow)
        result = await service.search(viewer_id=a, keyword="user")

        item_ids = {item.user_id for item in result.items}
        assert b not in item_ids
        assert c in item_ids

    async def test_excludes_suspended_users(self, uow, seed_users, session_factory):
        a, b, c = await seed_users(3)

        async with session_factory() as s:
            await s.execute(
                update(User).where(User.user_id == b).values(status=UserStatus.SUSPENDED)
            )
            await s.commit()

        service = FriendSearchService(uow=uow)
        result = await service.search(viewer_id=a, keyword="user")

        item_ids = {item.user_id for item in result.items}
        assert b not in item_ids
        assert c in item_ids

    async def test_excludes_users_blocked_by_me(
        self, uow, seed_users,
    ):
        a, b, c = await seed_users(3)

        block_service = UserBlockService(uow=uow)
        await block_service.block_user(user_id=a, target_user_id=b)

        search_service = FriendSearchService(uow=uow)
        result = await search_service.search(viewer_id=a, keyword="user")

        item_ids = {item.user_id for item in result.items}
        assert b not in item_ids
        assert c in item_ids

    async def test_excludes_users_who_blocked_me(
        self, uow, seed_users,
    ):
        """역방향 차단 — b 가 a 를 차단하면 a 검색 결과에 b 미노출."""
        a, b, c = await seed_users(3)

        block_service = UserBlockService(uow=uow)
        await block_service.block_user(user_id=b, target_user_id=a)

        search_service = FriendSearchService(uow=uow)
        result = await search_service.search(viewer_id=a, keyword="user")

        item_ids = {item.user_id for item in result.items}
        assert b not in item_ids
        assert c in item_ids

    async def test_excludes_users_without_detail(
        self, uow, seed_users, session_factory,
    ):
        """detail (2차 회원가입) 미존재 유저는 INNER JOIN 으로 자연 제외."""
        a, b, _ = await seed_users(3)

        async with session_factory() as s:
            await s.execute(
                delete(UserDetailInform).where(UserDetailInform.user_id == b)
            )
            await s.commit()

        search_service = FriendSearchService(uow=uow)
        result = await search_service.search(viewer_id=a, keyword=b)

        item_ids = {item.user_id for item in result.items}
        assert b not in item_ids


class TestMatching:
    async def test_matches_user_name_partial(self, uow, seed_users):
        """seed_users 는 user_name = user0/user1/user2 — "user1" 으로 b 만 매칭."""
        a, b, c = await seed_users(3)
        service = FriendSearchService(uow=uow)

        result = await service.search(viewer_id=a, keyword="user1")

        item_ids = {item.user_id for item in result.items}
        assert b in item_ids
        assert c not in item_ids

    async def test_matches_user_name_case_insensitive(self, uow, seed_users):
        a, b, _ = await seed_users(3)
        service = FriendSearchService(uow=uow)

        result = await service.search(viewer_id=a, keyword="USER1")

        item_ids = {item.user_id for item in result.items}
        assert b in item_ids

    async def test_matches_user_id_partial(self, uow, seed_users):
        """user_name 엔 없는 토큰이지만 user_id 에는 있는 키워드로 매칭."""
        a, b, _ = await seed_users(3)
        service = FriendSearchService(uow=uow)

        result = await service.search(viewer_id=a, keyword="IT_001")

        item_ids = {item.user_id for item in result.items}
        assert b in item_ids

    async def test_no_match_returns_empty(self, uow, seed_users):
        (a,) = await seed_users(1)
        service = FriendSearchService(uow=uow)

        result = await service.search(viewer_id=a, keyword="존재하지않는키워드XYZ")

        assert result.items == []
        assert result.next_cursor is None


class TestFriendshipMapping:
    async def test_pending_as_requester(self, uow, seed_users):
        a, b, _ = await seed_users(3)
        friendship_service = FriendshipService(uow=uow)
        await friendship_service.send_request(requester_id=a, addressee_id=b)

        search_service = FriendSearchService(uow=uow)
        result = await search_service.search(viewer_id=a, keyword="user1")

        item = next(it for it in result.items if it.user_id == b)
        assert item.friendship_status == FriendshipStatus.PENDING
        assert item.is_requester is True

    async def test_pending_as_addressee(self, uow, seed_users):
        a, b, _ = await seed_users(3)
        friendship_service = FriendshipService(uow=uow)
        await friendship_service.send_request(requester_id=b, addressee_id=a)

        search_service = FriendSearchService(uow=uow)
        result = await search_service.search(viewer_id=a, keyword="user1")

        item = next(it for it in result.items if it.user_id == b)
        assert item.friendship_status == FriendshipStatus.PENDING
        assert item.is_requester is False

    async def test_accepted_yields_null_is_requester(self, uow, seed_users):
        a, b, _ = await seed_users(3)
        friendship_service = FriendshipService(uow=uow)
        created = await friendship_service.send_request(requester_id=a, addressee_id=b)
        await friendship_service.accept_request(
            friendship_id=created.friendship_id, user_id=b,
        )

        search_service = FriendSearchService(uow=uow)
        result = await search_service.search(viewer_id=a, keyword="user1")

        item = next(it for it in result.items if it.user_id == b)
        assert item.friendship_status == FriendshipStatus.ACCEPTED
        assert item.is_requester is None

    async def test_rejected_yields_null_is_requester(self, uow, seed_users):
        a, b, _ = await seed_users(3)
        friendship_service = FriendshipService(uow=uow)
        created = await friendship_service.send_request(requester_id=a, addressee_id=b)
        await friendship_service.reject_request(
            friendship_id=created.friendship_id, user_id=b,
        )

        search_service = FriendSearchService(uow=uow)
        result = await search_service.search(viewer_id=a, keyword="user1")

        item = next(it for it in result.items if it.user_id == b)
        assert item.friendship_status == FriendshipStatus.REJECTED
        assert item.is_requester is None


class TestProfileFields:
    async def test_includes_travel_styles(self, uow, seed_users, session_factory):
        a, b, _ = await seed_users(3)

        async with session_factory() as s:
            s.add(UserTravelStyle(user_id=b, style=TravelStyle.FOOD_TOUR))
            s.add(UserTravelStyle(user_id=b, style=TravelStyle.ACTIVITY))
            await s.commit()

        search_service = FriendSearchService(uow=uow)
        result = await search_service.search(viewer_id=a, keyword="user1")

        item = next(it for it in result.items if it.user_id == b)
        assert set(item.travel_styles) == {TravelStyle.FOOD_TOUR, TravelStyle.ACTIVITY}

    async def test_returns_public_profile_fields_only(self, uow, seed_users):
        """민감 정보(email, phone_number, age, gender 등) 는 응답 DTO 에 없음."""
        a, b, _ = await seed_users(3)
        service = FriendSearchService(uow=uow)

        result = await service.search(viewer_id=a, keyword="user1")

        item = next(it for it in result.items if it.user_id == b)
        assert hasattr(item, "user_id")
        assert hasattr(item, "user_name")
        assert hasattr(item, "nationality")
        assert hasattr(item, "travel_styles")
        assert hasattr(item, "profile_image_url")
        # 민감 정보 미노출
        assert not hasattr(item, "email")
        assert not hasattr(item, "phone_number")
        assert not hasattr(item, "age")
        assert not hasattr(item, "gender")


class TestPagination:
    async def test_first_page_returns_30_with_cursor_then_partial_no_cursor(
        self, uow, seed_users,
    ):
        """35명 시드 → viewer 1명 제외 = 34명. 30개 (page1) + 4개 (page2)."""
        user_ids = await seed_users(35)
        viewer = user_ids[0]
        service = FriendSearchService(uow=uow)

        page1 = await service.search(viewer_id=viewer, keyword="user")

        assert len(page1.items) == PAGE_SIZE
        assert page1.next_cursor is not None

        page2 = await service.search(
            viewer_id=viewer, keyword="user", cursor=page1.next_cursor,
        )

        assert len(page2.items) == 34 - PAGE_SIZE
        assert page2.next_cursor is None

        page1_ids = {item.user_id for item in page1.items}
        page2_ids = {item.user_id for item in page2.items}
        assert page1_ids.isdisjoint(page2_ids)
        assert viewer not in (page1_ids | page2_ids)
        assert page1_ids | page2_ids == set(user_ids[1:])
