import pytest

from app.domain.auth.service.profile import ProfileService

from test.unit.domain.auth.mock_factory import (
    FakeUnitOfWork,
    make_mock_session,
    make_object_storage_mock,
    make_user_detail_repo_mock,
    make_user_repo_mock,
)


@pytest.fixture
def mock_session():
    return make_mock_session()


@pytest.fixture
def user_repo_mock():
    return make_user_repo_mock()


@pytest.fixture
def user_detail_repo_mock():
    return make_user_detail_repo_mock()


@pytest.fixture
def storage_mock():
    return make_object_storage_mock()


@pytest.fixture
def service(
    monkeypatch, mock_session,
    user_repo_mock, user_detail_repo_mock, storage_mock,
):
    """Mock 레포 + Storage 가 주입된 ProfileService."""
    monkeypatch.setattr(
        "app.domain.auth.service.profile.UserRepository",
        lambda session: user_repo_mock,
    )
    monkeypatch.setattr(
        "app.domain.auth.service.profile.UserDetailInformRepository",
        lambda session: user_detail_repo_mock,
    )
    monkeypatch.setattr(
        "app.domain.auth.service.profile.get_object_storage",
        lambda: storage_mock,
    )

    uow = FakeUnitOfWork(mock_session)
    return ProfileService(uow=uow)
