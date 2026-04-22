"""RoomService 단위 테스트용 Mock 팩토리."""
from unittest.mock import AsyncMock, MagicMock


class FakeAsyncContextManager:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeUnitOfWork:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        return False


def make_mock_session() -> MagicMock:
    session = MagicMock(name="session")
    session.flush = AsyncMock()
    session.refresh = AsyncMock()
    session.begin_nested = MagicMock(return_value=FakeAsyncContextManager())
    return session


def make_chat_room_repo_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.save.return_value = None
    mock.find_by_id.return_value = None
    mock.find_direct_by_pair.return_value = None
    mock.find_rooms_of_user.return_value = []
    mock.update_last_message.return_value = None
    return mock


def make_chat_member_repo_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.save.return_value = None
    mock.save_all.return_value = None
    mock.find.return_value = None
    mock.find_active_member_ids.return_value = []
    mock.is_active_member.return_value = False
    mock.find_user_room_ids.return_value = []
    return mock


def make_user_block_repo_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.find_blocks_between.return_value = []
    return mock


def make_user_repo_mock() -> AsyncMock:
    mock = AsyncMock()
    mock.find_by_id_with_profile.return_value = None
    return mock


def make_fanout_mock() -> MagicMock:
    fanout = MagicMock(name="fanout")
    fanout.fan_out_to_session = AsyncMock()
    fanout.fan_out_to_user = AsyncMock()
    fanout.fan_out_to_room = AsyncMock()
    return fanout


def make_redis_mock() -> MagicMock:
    redis = MagicMock(name="redis")
    redis._pipes: list = []

    pipe = MagicMock(name="pipeline")
    pipe.sadd = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock()

    def _new_pipe(*_a, **_kw):
        p = MagicMock(name="pipeline")
        p.sadd = MagicMock(return_value=p)
        p.expire = MagicMock(return_value=p)
        p.execute = AsyncMock()
        redis._pipes.append(p)
        return p

    redis.pipeline = MagicMock(side_effect=_new_pipe)
    return redis
