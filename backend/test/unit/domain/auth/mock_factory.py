"""auth 도메인 단위 테스트 공용 Mock 팩토리."""
from unittest.mock import AsyncMock, MagicMock


class FakeUnitOfWork:
    """`@transactional` 데코레이터의 `async with self.uow as session:` 패턴 충족."""

    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def make_mock_session() -> MagicMock:
    session = MagicMock(name="session")
    session.flush = AsyncMock()
    return session


# ──────────────────── Repository mocks ────────────────────

def make_user_repo_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.find_by_id.return_value = None
    mock.find_by_id_with_profile.return_value = None
    mock.find_by_ids_with_profile.return_value = {}
    mock.update.return_value = None
    return mock


def make_user_detail_repo_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.find_by_user_id.return_value = None
    mock.update.return_value = None
    return mock


def make_object_storage_mock() -> MagicMock:
    """이미지 업/삭제 관련 — 본 테스트에서는 호출 안 됨 (get_my_profile 만 cover)."""
    storage = MagicMock(name="storage")
    storage.upload_perm = AsyncMock()
    storage.delete = AsyncMock()
    return storage
