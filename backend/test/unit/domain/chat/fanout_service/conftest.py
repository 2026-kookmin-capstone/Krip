from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

import pytest

from app.domain.chat.service.fanout_service import FanoutService


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
    return ws


@pytest.fixture
def fanout() -> FanoutService:
    """FANOUT_MODE=in_process (기본값) 에서 정상 생성."""
    return FanoutService()
