"""feed 도메인 단위 테스트 공용 Mock 팩토리.

`@transactional` 의 `async with self.uow as session:` 패턴을 충족하는 FakeUnitOfWork +
FeedPostRepository / ObjectStorage 의 AsyncMock 을 한 곳에서 만든다.
"""
from unittest.mock import AsyncMock, MagicMock


class FakeUnitOfWork:
    """`@transactional` 데코레이터의 컨텍스트 매니저 인터페이스 충족."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def make_mock_session() -> MagicMock:
    session = MagicMock(name="session")
    session.flush = AsyncMock()
    session.delete = AsyncMock()
    session.get = AsyncMock(return_value=None)
    return session


def make_feed_post_repo_mock() -> AsyncMock:
    """FeedPostRepository 의 모든 public 메서드를 AsyncMock 으로."""
    mock = AsyncMock()
    mock.find_by_post_id.return_value = None
    mock.find_by_owner.return_value = []
    mock.save.side_effect = lambda post: post
    mock.update.side_effect = lambda post: post
    mock.delete.return_value = None
    return mock


def make_object_storage_mock() -> MagicMock:
    storage = MagicMock(name="storage")
    storage.upload_to_key = AsyncMock()
    storage.delete_by_prefix = AsyncMock()
    return storage


def make_friendship_repo_mock() -> AsyncMock:
    """FriendshipRepository — `_resolve_viewer_visibilities` 가 `find_between` 만 사용."""
    mock = AsyncMock()
    mock.find_between.return_value = None  # 기본: 관계 없음
    return mock


def make_user_block_repo_mock() -> AsyncMock:
    """UserBlockRepository — `_resolve_viewer_visibilities` 가 `find_blocks_between` 만 사용."""
    mock = AsyncMock()
    mock.find_blocks_between.return_value = []  # 기본: 차단 없음
    return mock
