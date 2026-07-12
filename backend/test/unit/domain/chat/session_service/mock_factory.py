"""SessionService 단위 테스트용 Mock Redis / FanoutService."""
from unittest.mock import AsyncMock, MagicMock


def make_mock_pipeline() -> MagicMock:
    """redis-py pipeline 체인 — 모든 명령이 self 반환, execute 는 AsyncMock."""
    pipe = MagicMock(name="pipeline")
    pipe.hset = MagicMock(return_value=pipe)
    pipe.expire = MagicMock(return_value=pipe)
    pipe.zadd = MagicMock(return_value=pipe)
    pipe.set = MagicMock(return_value=pipe)
    pipe.delete = MagicMock(return_value=pipe)
    pipe.zrem = MagicMock(return_value=pipe)
    pipe.execute = AsyncMock(return_value=[])
    return pipe


def make_mock_redis() -> MagicMock:
    """SessionService 가 호출하는 메서드만 Mock 제공.

    `redis._pipes` 리스트에 pipeline() 호출마다 생성된 pipe 가 쌓여 테스트에서
    호출 시퀀스를 역추적할 수 있다.
    """
    redis = MagicMock(name="redis")
    redis._pipes: list[MagicMock] = []

    redis.hset = AsyncMock(return_value=1)
    redis.exists = AsyncMock(return_value=1)
    redis.hget = AsyncMock(return_value=None)
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)
    redis.zremrangebyscore = AsyncMock(return_value=0)
    redis.zcard = AsyncMock(return_value=0)
    redis.zrange = AsyncMock(return_value=[])

    def _new_pipe(*_a, **_kw):
        p = make_mock_pipeline()
        redis._pipes.append(p)
        return p

    redis.pipeline = MagicMock(side_effect=_new_pipe)
    return redis


def make_mock_fanout() -> MagicMock:
    fanout = MagicMock(name="fanout")
    fanout.fan_out_to_session = AsyncMock()
    fanout.fan_out_to_user = AsyncMock()
    fanout.fan_out_to_room = AsyncMock()
    return fanout
