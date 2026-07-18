"""BearerTokenMiddleware / RegisterCheckMiddleware — dispatch 레벨 단위 테스트.

httpx TestClient 는 non-ASCII 헤더를 ascii 로 인코딩하려다 거부하므로, non-ASCII 토큰
회귀는 ASGI scope 를 직접 구성해 dispatch 를 호출해 검증한다.
"""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request
from starlette.responses import Response

from app.config.setting import settings
from app.domain.auth.model.user import UserStatus
from app.middleware.auth import BearerTokenMiddleware, RegisterCheckMiddleware


pytestmark = pytest.mark.unit


def _http_request(headers: list[tuple[bytes, bytes]], *, path="/protected", state=None) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": headers,
        "scheme": "http",
        "server": ("test", 80),
        "client": ("test", 1),
        "state": state or {},
    }
    return Request(scope)


class _CallNextSpy:
    """dispatch 가 통과시켰는지 추적하는 call_next 대역."""

    def __init__(self):
        self.called = False

    async def __call__(self, request: Request) -> Response:
        self.called = True
        return Response(status_code=200)


class TestBearerTokenMiddleware:
    def _mw(self) -> BearerTokenMiddleware:
        return BearerTokenMiddleware(app=lambda *a, **k: None)

    async def test_non_ascii_token_returns_401_not_500(self):
        """raw non-ASCII 바이트(0xE9) Authorization → 401. bytes 인코딩 전이면
        str compare_digest 가 TypeError → 500 이었다."""
        req = _http_request([(b"authorization", b"Bearer caf\xe9")])
        spy = _CallNextSpy()

        resp = await self._mw().dispatch(req, spy)

        assert resp.status_code == 401
        assert spy.called is False

    async def test_wrong_ascii_token_returns_401(self):
        req = _http_request([(b"authorization", b"Bearer wrong-token")])
        spy = _CallNextSpy()

        resp = await self._mw().dispatch(req, spy)

        assert resp.status_code == 401
        assert spy.called is False

    async def test_valid_token_passes_through(self):
        token = settings.ACCESS_TOKEN
        req = _http_request([(b"authorization", f"Bearer {token}".encode("utf-8"))])
        spy = _CallNextSpy()

        resp = await self._mw().dispatch(req, spy)

        assert resp.status_code == 200
        assert spy.called is True

    async def test_excluded_path_bypasses(self):
        req = _http_request([], path="/health")
        spy = _CallNextSpy()

        resp = await self._mw().dispatch(req, spy)

        assert resp.status_code == 200
        assert spy.called is True


class _FakeUow:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, *a):
        return False


class TestRegisterCheckSuspended:
    def _request(self, user_id="USER_x") -> Request:
        fake_app = SimpleNamespace(container=SimpleNamespace(uow=lambda: _FakeUow()))
        req = _http_request([], state={"user_id": user_id, "request_id": "rid"})
        req.scope["app"] = fake_app
        return req

    def _patch(self, monkeypatch, *, user, cache_exists=False):
        cache = SimpleNamespace(
            exists=AsyncMock(return_value=cache_exists),
            set_flag=AsyncMock(),
        )
        monkeypatch.setattr(
            "app.middleware.auth.get_redis_cache_manager", lambda: cache,
            raising=False,
        )
        access_state = None if user is None else (
            user.status, user.detail is not None,
        )
        repo = SimpleNamespace(find_access_state=AsyncMock(return_value=access_state))
        cache.repo = repo
        monkeypatch.setattr(
            "app.domain.auth.repository.user.UserRepository", lambda session: repo,
        )
        return cache

    async def test_positive_cache_cannot_bypass_inactive_status(self, monkeypatch):
        user = SimpleNamespace(status=UserStatus.INACTIVE, detail=object())
        cache = self._patch(monkeypatch, user=user, cache_exists=True)
        spy = _CallNextSpy()

        resp = await RegisterCheckMiddleware(app=lambda *a, **k: None).dispatch(
            self._request(), spy,
        )

        assert resp.status_code == 419
        assert spy.called is False
        cache.repo.find_access_state.assert_awaited_once_with("USER_x")

    async def test_suspended_user_blocked_with_403_and_not_cached(self, monkeypatch):
        user = SimpleNamespace(status=UserStatus.SUSPENDED, detail=object())
        cache = self._patch(monkeypatch, user=user)
        spy = _CallNextSpy()

        resp = await RegisterCheckMiddleware(app=lambda *a, **k: None).dispatch(
            self._request(), spy,
        )

        assert resp.status_code == 403
        assert json.loads(resp.body)["status"] == "suspended"
        assert spy.called is False
        # 정지 유저를 양성으로 캐싱하면 24h 동안 밴이 마스킹됨 → set_flag 호출 금지
        cache.set_flag.assert_not_awaited()

    async def test_active_user_passes_without_authorization_cache(self, monkeypatch):
        user = SimpleNamespace(status=UserStatus.ACTIVE, detail=object())
        cache = self._patch(monkeypatch, user=user)
        spy = _CallNextSpy()

        resp = await RegisterCheckMiddleware(app=lambda *a, **k: None).dispatch(
            self._request(), spy,
        )

        assert resp.status_code == 200
        assert spy.called is True
        cache.exists.assert_not_awaited()
        cache.set_flag.assert_not_awaited()
