"""OAuthClient 의 vendor(httpx) 예외 → 도메인 예외 변환 단위 테스트.

핵심 회귀 검증 (Bug: 만료/재사용 code 콜백이 500 으로 새던 문제 수정):
    - vendor 4xx (만료·재사용 code 등)      → OAuthInvalidGrantError (라우터 400)
    - access_token 누락 (→ Bearer None 버킷) → OAuthInvalidGrantError
    - vendor 5xx / 네트워크 오류             → OAuthVendorError (라우터 502)
    - 예외 메시지에 vendor 응답 본문·PII 를 싣지 않는다.
"""
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from app.config.oauth import OAuthProvider
from app.core.oauth.exception import OAuthInvalidGrantError, OAuthVendorError
from app.core.oauth.google import GoogleOAuthClient


def _mk_config() -> MagicMock:
    config = MagicMock()
    config.client_id = "cid"
    config.client_secret = "secret"
    config.redirect_uri = "https://api.example.com/callback"
    config.token_url = "https://oauth.example.com/token"
    config.userinfo_url = "https://oauth.example.com/userinfo"
    return config


def _mk_response(status_code: int, json_body=None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    if status_code >= 400:
        request = httpx.Request("POST", "https://oauth.example.com/token")
        err_resp = httpx.Response(status_code, request=request, text="vendor-secret-body")
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "err", request=request, response=err_resp,
        )
    else:
        resp.raise_for_status.return_value = None
    return resp


def _client() -> GoogleOAuthClient:
    client = GoogleOAuthClient(_mk_config())
    client.client = MagicMock()
    return client


@pytest.mark.unit
class TestAccessTokenErrorMapping:
    async def test_vendor_4xx_maps_to_invalid_grant(self):
        client = _client()
        client.client.post = AsyncMock(return_value=_mk_response(400))

        with pytest.raises(OAuthInvalidGrantError) as exc:
            await client.get_access_token(code="reused", user_type="callback")
        # vendor 응답 본문(민감 정보 가능) 이 메시지에 노출되지 않는다.
        assert "vendor-secret-body" not in str(exc.value)

    async def test_vendor_5xx_maps_to_vendor_error(self):
        client = _client()
        client.client.post = AsyncMock(return_value=_mk_response(503))

        with pytest.raises(OAuthVendorError):
            await client.get_access_token(code="c", user_type="callback")

    async def test_network_error_maps_to_vendor_error(self):
        client = _client()
        client.client.post = AsyncMock(
            side_effect=httpx.ConnectError("connection refused"),
        )

        with pytest.raises(OAuthVendorError):
            await client.get_access_token(code="c", user_type="callback")

    async def test_missing_access_token_maps_to_invalid_grant(self):
        client = _client()
        client.client.post = AsyncMock(return_value=_mk_response(200, json_body={}))

        with pytest.raises(OAuthInvalidGrantError):
            await client.get_access_token(code="c", user_type="callback")

    async def test_success_returns_token(self):
        client = _client()
        client.client.post = AsyncMock(
            return_value=_mk_response(200, json_body={"access_token": "tok"}),
        )

        token = await client.get_access_token(code="c", user_type="callback")
        assert token == "tok"


@pytest.mark.unit
class TestUserInfoErrorMapping:
    async def test_userinfo_4xx_maps_to_invalid_grant(self):
        """Bearer None(만료 token) 등으로 userinfo 가 401 → 401 이 500 으로 새지 않게 매핑."""
        client = _client()
        client.client.get = AsyncMock(return_value=_mk_response(401))

        with pytest.raises(OAuthInvalidGrantError):
            await client.get_user_info(access_token="None")

    async def test_userinfo_5xx_maps_to_vendor_error(self):
        client = _client()
        client.client.get = AsyncMock(return_value=_mk_response(500))

        with pytest.raises(OAuthVendorError):
            await client.get_user_info(access_token="tok")

    async def test_userinfo_success_returns_user(self):
        client = _client()
        client.client.get = AsyncMock(
            return_value=_mk_response(200, json_body={"id": "uid", "email": "e", "name": "n"}),
        )

        user = await client.get_user_info(access_token="tok")
        assert user.id == "uid"
        assert user.provider == OAuthProvider.GOOGLE
