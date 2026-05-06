import pytest

from app.domain.feed.service.feed_post import FeedPostService

from test.unit.domain.feed.mock_factory import (
    FakeUnitOfWork,
    make_feed_post_repo_mock,
    make_mock_session,
    make_object_storage_mock,
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
def service(monkeypatch, mock_session, repo_mock, storage_mock):
    """FeedPostRepository 와 ObjectStorage 가 모두 mock 으로 주입된 서비스."""
    monkeypatch.setattr(
        "app.domain.feed.service.feed_post.FeedPostRepository",
        lambda session: repo_mock,
    )
    monkeypatch.setattr(
        "app.domain.feed.service.feed_post.get_object_storage",
        lambda: storage_mock,
    )

    uow = FakeUnitOfWork(mock_session)
    return FeedPostService(uow=uow)
