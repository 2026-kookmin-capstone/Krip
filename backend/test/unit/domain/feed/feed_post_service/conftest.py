import pytest

from app.domain.feed.service.feed_post import FeedPostService

from test.unit.domain.feed.mock_factory import (
    FakeUnitOfWork,
    make_feed_post_repo_mock,
    make_friendship_repo_mock,
    make_mock_session,
    make_object_storage_mock,
    make_user_block_repo_mock,
)


@pytest.fixture
def mock_session():
    return make_mock_session()


@pytest.fixture
def repo_mock():
    return make_feed_post_repo_mock()


@pytest.fixture
def storage_mock():
    return make_object_storage_mock()


@pytest.fixture
def friendship_repo_mock():
    return make_friendship_repo_mock()


@pytest.fixture
def block_repo_mock():
    return make_user_block_repo_mock()


@pytest.fixture
def service(
    monkeypatch, mock_session,
    repo_mock, storage_mock, friendship_repo_mock, block_repo_mock,
):
    """FeedPostRepository / ObjectStorage / Friendship / UserBlock 모두 mock 주입.

    `_resolve_viewer_visibilities` 가 `FriendshipRepository(self._session)` /
    `UserBlockRepository(self._session)` 를 직접 인스턴스화하므로 양쪽 모두 monkeypatch.
    """
    monkeypatch.setattr(
        "app.domain.feed.service.feed_post.FeedPostRepository",
        lambda session: repo_mock,
    )
    monkeypatch.setattr(
        "app.domain.feed.service.feed_post.FriendshipRepository",
        lambda session: friendship_repo_mock,
    )
    monkeypatch.setattr(
        "app.domain.feed.service.feed_post.UserBlockRepository",
        lambda session: block_repo_mock,
    )
    monkeypatch.setattr(
        "app.domain.feed.service.feed_post.get_object_storage",
        lambda: storage_mock,
    )

    uow = FakeUnitOfWork(mock_session)
    return FeedPostService(uow=uow)
