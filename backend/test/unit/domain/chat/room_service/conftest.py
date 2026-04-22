import pytest

from app.domain.chat.service.room_service import RoomService

from test.unit.domain.chat.room_service.mock_factory import (
    FakeUnitOfWork,
    make_chat_member_repo_mock,
    make_chat_room_repo_mock,
    make_fanout_mock,
    make_mock_session,
    make_redis_mock,
    make_user_block_repo_mock,
    make_user_repo_mock,
)
from test.unit.domain.chat.room_service.model_factory import (
    ChatRoomFactory,
    UserBlockFactory,
    UserFactory,
)


@pytest.fixture(autouse=True)
def reset_factories():
    UserFactory.reset_counter()
    ChatRoomFactory.reset_counter()
    UserBlockFactory.reset_counter()
    yield
    UserFactory.reset_counter()
    ChatRoomFactory.reset_counter()
    UserBlockFactory.reset_counter()


@pytest.fixture
def mock_session():
    return make_mock_session()


@pytest.fixture
def chat_room_repo_mock():
    return make_chat_room_repo_mock()


@pytest.fixture
def chat_member_repo_mock():
    return make_chat_member_repo_mock()


@pytest.fixture
def user_block_repo_mock():
    return make_user_block_repo_mock()


@pytest.fixture
def user_repo_mock():
    return make_user_repo_mock()


@pytest.fixture
def fanout_mock():
    return make_fanout_mock()


@pytest.fixture
def redis_mock():
    return make_redis_mock()


@pytest.fixture
def service(
    monkeypatch,
    mock_session,
    chat_room_repo_mock,
    chat_member_repo_mock,
    user_block_repo_mock,
    user_repo_mock,
    fanout_mock,
    redis_mock,
):
    """Mock 레포 + Mock Redis / Fanout 이 주입된 RoomService."""
    monkeypatch.setattr(
        "app.domain.chat.service.room_service.ChatRoomRepository",
        lambda session: chat_room_repo_mock,
    )
    monkeypatch.setattr(
        "app.domain.chat.service.room_service.ChatRoomMemberRepository",
        lambda session: chat_member_repo_mock,
    )
    monkeypatch.setattr(
        "app.domain.chat.service.room_service.UserBlockRepository",
        lambda session: user_block_repo_mock,
    )
    monkeypatch.setattr(
        "app.domain.chat.service.room_service.UserRepository",
        lambda session: user_repo_mock,
    )

    async def _get_client():
        return redis_mock
    monkeypatch.setattr(
        "app.domain.chat.service.room_service.get_redis_client",
        _get_client,
    )

    uow = FakeUnitOfWork(mock_session)
    return RoomService(uow=uow, fanout_service=fanout_mock)
