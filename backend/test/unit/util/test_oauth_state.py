"""OAuth state CSRF 유틸(app.util.oauth_state) 단위 테스트.

- 웹: nonce 생성 / 쿠키 double-submit 상수시간 검증 / 쿠키 속성 / 제거
- 앱: Redis 단발성 nonce 저장(TTL)·소비 — 부재/만료/재사용(replay) 거부

`get_redis_client` 는 모듈 함수 — async 로 monkeypatch (실 Redis 비접근).
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from starlette.responses import Response

from app.util import oauth_state
from app.util.oauth_state import (
    STATE_COOKIE_NAME,
    consume_state_nonce,
    generate_state_nonce,
    store_state_nonce,
    verify_state_nonce,
)


def _request_with_cookies(**cookies) -> SimpleNamespace:
    """verify_state_nonce 는 request.cookies.get 만 사용 — 최소 흉내."""
    return SimpleNamespace(cookies=cookies)


@pytest.mark.unit
class TestGenerateStateNonce:
    def test_returns_urlsafe_token(self):
        nonce = generate_state_nonce()
        assert isinstance(nonce, str) and len(nonce) >= 32
        # url-safe — state 파싱(split)·URL 전송에 안전한 문자만
        assert not (set(nonce) & set(":/+= "))

    def test_is_unique_per_call(self):
        assert generate_state_nonce() != generate_state_nonce()


@pytest.mark.unit
class TestVerifyStateNonce:
    def test_passes_when_cookie_matches_nonce(self):
        verify_state_nonce(_request_with_cookies(oauth_state="n1"), "n1")

    def test_rejects_when_cookie_missing(self):
        with pytest.raises(HTTPException) as exc:
            verify_state_nonce(_request_with_cookies(), "n1")
        assert exc.value.status_code == 400

    def test_rejects_when_mismatch(self):
        with pytest.raises(HTTPException) as exc:
            verify_state_nonce(_request_with_cookies(oauth_state="n1"), "n2")
        assert exc.value.status_code == 400

    def test_rejects_when_nonce_empty(self):
        with pytest.raises(HTTPException) as exc:
            verify_state_nonce(_request_with_cookies(oauth_state="present"), "")
        assert exc.value.status_code == 400

    def test_rejects_non_ascii_nonce_with_400_not_typeerror(self):
        """non-ASCII nonce(state 쿼리 파라미터) → 400. bytes 비교 전이면 str compare_digest
        가 TypeError 를 던져 400 대신 500 이 됐다."""
        with pytest.raises(HTTPException) as exc:
            verify_state_nonce(_request_with_cookies(oauth_state="present"), "café")
        assert exc.value.status_code == 400


@pytest.mark.unit
class TestStateCookie:
    def test_set_state_cookie_has_security_attributes(self):
        resp = Response()
        oauth_state.set_state_cookie(resp, "nonce123")
        header = resp.headers.get("set-cookie")
        low = header.lower()
        assert f"{STATE_COOKIE_NAME}=nonce123" in header
        assert "httponly" in low
        assert "secure" in low
        assert "samesite=lax" in low
        assert "path=/api/auth/login" in low
        assert "max-age=600" in low

    def test_clear_state_cookie_expires_it(self):
        resp = Response()
        oauth_state.clear_state_cookie(resp)
        low = resp.headers.get("set-cookie").lower()
        assert STATE_COOKIE_NAME in low
        assert "max-age=0" in low


@pytest.mark.unit
class TestStoreStateNonce:
    async def test_stores_nonce_with_ttl_and_returns_it(self, monkeypatch):
        redis = AsyncMock()
        monkeypatch.setattr(oauth_state, "get_redis_client", AsyncMock(return_value=redis))

        nonce = await store_state_nonce()

        assert isinstance(nonce, str) and nonce
        redis.set.assert_awaited_once()
        args, kwargs = redis.set.call_args
        assert args[0] == f"oauth_state:{nonce}"
        assert kwargs.get("ex") == 600


@pytest.mark.unit
class TestConsumeStateNonce:
    async def test_consumes_existing_nonce(self, monkeypatch):
        redis = AsyncMock()
        redis.delete = AsyncMock(return_value=1)
        monkeypatch.setattr(oauth_state, "get_redis_client", AsyncMock(return_value=redis))

        await consume_state_nonce("n1")
        redis.delete.assert_awaited_once_with("oauth_state:n1")

    async def test_rejects_missing_or_replayed_nonce(self, monkeypatch):
        redis = AsyncMock()
        redis.delete = AsyncMock(return_value=0)  # 0건 = 부재/만료/재사용
        monkeypatch.setattr(oauth_state, "get_redis_client", AsyncMock(return_value=redis))

        with pytest.raises(HTTPException) as exc:
            await consume_state_nonce("n1")
        assert exc.value.status_code == 400

    async def test_rejects_empty_nonce_without_touching_redis(self, monkeypatch):
        redis = AsyncMock()
        monkeypatch.setattr(oauth_state, "get_redis_client", AsyncMock(return_value=redis))

        with pytest.raises(HTTPException) as exc:
            await consume_state_nonce("")
        assert exc.value.status_code == 400
        redis.delete.assert_not_awaited()
