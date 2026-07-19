"""L-3 cursor repositories의 lookahead query limit 계약."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.feed.repository.feed_post_comment import PAGE_SIZE as COMMENT_PAGE_SIZE
from app.domain.feed.repository.feed_post_comment import FeedPostCommentRepository
from app.domain.friend.repository.friendship import PAGE_SIZE as FRIENDSHIP_PAGE_SIZE
from app.domain.friend.repository.friendship import FriendshipRepository
from app.domain.friend.repository.search import PAGE_SIZE as SEARCH_PAGE_SIZE
from app.domain.friend.repository.search import FriendSearchRepository
from app.domain.friend.repository.user_block import PAGE_SIZE as BLOCK_PAGE_SIZE
from app.domain.friend.repository.user_block import UserBlockRepository
from app.domain.tripmate.repository.tripmate_post import PAGE_SIZE as TRIPMATE_PAGE_SIZE
from app.domain.tripmate.repository.tripmate_post import TripmatePostRepository


def _session() -> MagicMock:
    result = MagicMock()
    result.all.return_value = []
    result.unique.return_value.scalars.return_value.all.return_value = []
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


def _assert_limit(session: MagicMock, expected: int) -> None:
    stmt = session.execute.await_args.args[0]
    assert stmt._limit_clause.value == expected


@pytest.mark.unit
async def test_comment_query_uses_lookahead_limit():
    session = _session()
    await FeedPostCommentRepository(session).find_by_post(
        post_id="FDP_x", viewer_id="USER_x",
    )
    _assert_limit(session, COMMENT_PAGE_SIZE + 1)


@pytest.mark.unit
async def test_friend_search_query_uses_lookahead_limit():
    session = _session()
    await FriendSearchRepository(session).search_active_users(
        viewer_id="USER_x", keyword="x",
    )
    _assert_limit(session, SEARCH_PAGE_SIZE + 1)


@pytest.mark.unit
async def test_block_query_uses_lookahead_limit():
    session = _session()
    await UserBlockRepository(session).find_blocks_by_user("USER_x")
    _assert_limit(session, BLOCK_PAGE_SIZE + 1)


@pytest.mark.unit
@pytest.mark.parametrize(
    "method_name",
    ["find_friends", "find_received_requests", "find_sent_requests"],
)
async def test_friendship_queries_use_lookahead_limit(method_name: str):
    session = _session()
    repo = FriendshipRepository(session)
    await getattr(repo, method_name)("USER_x")
    _assert_limit(session, FRIENDSHIP_PAGE_SIZE + 1)


@pytest.mark.unit
@pytest.mark.parametrize("method_name", ["find_all_displayed", "search"])
async def test_tripmate_queries_use_lookahead_limit(method_name: str):
    session = _session()
    repo = TripmatePostRepository(session)
    if method_name == "search":
        await repo.search("제주", user_id="USER_x")
    else:
        await repo.find_all_displayed(user_id="USER_x")
    _assert_limit(session, TRIPMATE_PAGE_SIZE + 1)
