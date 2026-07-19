from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.chat.service.fanout import FanoutService


def make_ws(session_id: str, user_id: str) -> MagicMock:
    """FanoutService 가 duck typing 으로 기대하는 WS 객체.

    - `session_id` / `user_id` / `subscribed_rooms` 속성
    - `send_json` 은 AsyncMock
    """
    ws = MagicMock(name=f"ws-{session_id}")
    ws.session_id = session_id
    ws.user_id = user_id
    ws.subscribed_rooms = set()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return ws


def authorization_scope(value=None, *, error: Exception | None = None):
    @asynccontextmanager
    async def scope():
        if error is not None:
            raise error
        yield value

    return scope()


@pytest.fixture
def fanout(monkeypatch) -> FanoutService:
    """FANOUT_MODE=in_process 를 명시 고정해 로컬 .env 오버라이드(node_channel)
    영향으로 실제 Redis 연결을 시도하지 않도록 한다.
    """
    from app.config import setting as setting_module
    monkeypatch.setattr(setting_module.settings, "FANOUT_MODE", "in_process")
    authorization = MagicMock()
    authorization.lock_room_delivery = MagicMock(
        side_effect=lambda _room_id, user_ids, **_kwargs: authorization_scope(set(user_ids)),
    )
    authorization.lock_user_delivery = MagicMock(
        side_effect=lambda _user_id: authorization_scope(True),
    )
    authorization.lock_room_subscription = MagicMock(
        side_effect=lambda _room_id, _user_id: authorization_scope(True),
    )
    authorization.prepare_current_message_event = AsyncMock(return_value=True)
    return FanoutService(authorization_service=authorization)
