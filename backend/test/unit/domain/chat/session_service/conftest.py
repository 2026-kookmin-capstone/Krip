from unittest.mock import AsyncMock

import pytest

from app.domain.chat.service.session import SessionService
from test.unit.domain.chat.session_service.mock_factory import (
    make_mock_fanout,
    make_mock_redis,
)


@pytest.fixture
def fanout_mock():
    return make_mock_fanout()


@pytest.fixture
def redis_mock():
    return make_mock_redis()


@pytest.fixture
def create_session_script(monkeypatch):
    script = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "app.domain.chat.service.session.lua_scripts.create_session", script,
    )
    return script


@pytest.fixture
def heartbeat_script(monkeypatch):
    script = AsyncMock(return_value=1)
    monkeypatch.setattr(
        "app.domain.chat.service.session.lua_scripts.heartbeat_session", script,
    )
    return script


@pytest.fixture
def revoke_all_sessions_script(monkeypatch):
    script = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "app.domain.chat.service.session.lua_scripts.revoke_all_sessions", script,
    )
    return script


@pytest.fixture
def service(
    monkeypatch, redis_mock, fanout_mock, create_session_script, heartbeat_script,
    revoke_all_sessions_script,
):
    """Mock Redis / Fanout 이 주입된 SessionService."""
    async def _get_client():
        return redis_mock

    monkeypatch.setattr(
        "app.domain.chat.service.session.get_redis_client",
        _get_client,
    )
    return SessionService(fanout_service=fanout_mock)
