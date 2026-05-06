"""FeedPostCommentService 단위 테스트 fixtures."""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.feed.model.feed_post import FeedPost, FeedVisibility
from app.domain.feed.service.feed_post_comment import FeedPostCommentService

from test.unit.domain.feed.mock_factory import FakeUnitOfWork, make_mock_session


@pytest.fixture
def mock_session():
    return make_mock_session()


@pytest.fixture
def comment_repo_mock():
    mock = AsyncMock()
    mock.find_by_id.return_value = None
    mock.find_by_post.return_value = []
    mock.count_by_post.return_value = 0
    mock.save.side_effect = lambda c: c
    mock.delete.return_value = None
    return mock


@pytest.fixture
def viewable_post_stub():
    post = MagicMock(spec=FeedPost)
    post.post_id = "FDP_x"
    post.user_id = "USER_owner"
    post.visibility = FeedVisibility.PUBLIC
    post.caption = None
    post.original_url = post.thumbnail_small_url = post.thumbnail_medium_url = "https://x"
    post.created_at = post.updated_at = datetime.now(timezone.utc)
    return post


@pytest.fixture
def service(monkeypatch, mock_session, comment_repo_mock, viewable_post_stub):
    monkeypatch.setattr(
        "app.domain.feed.service.feed_post_comment.FeedPostCommentRepository",
        lambda session: comment_repo_mock,
    )

    async def _stub_load(session, *, viewer_id, post_id):
        return viewable_post_stub
    monkeypatch.setattr(
        "app.domain.feed.service.feed_post_comment.load_viewable_post",
        _stub_load,
    )

    return FeedPostCommentService(uow=FakeUnitOfWork(mock_session))
