from abc import ABC, abstractmethod
from typing import Awaitable, Optional
from urllib.parse import urlencode

from httpx import AsyncClient, HTTPStatusError, RequestError, Response

from app.config.oauth import OAuthConfig, OAuthProvider
from app.core.oauth.exception import OAuthInvalidGrantError, OAuthVendorError


_INVALID_GRANT_MESSAGE = "인증이 만료되었거나 이미 사용된 요청입니다. 다시 로그인해주세요."
_VENDOR_ERROR_MESSAGE = "OAuth 제공자와 통신하지 못했습니다. 잠시 후 다시 시도해주세요."


class OAuthUser:
    def __init__(self, id: str, provider: OAuthProvider, email: Optional[str] = None, name: Optional[str] = None):
        self.id = id
        self.provider = provider
        self.email = email
        self.name = name


class OAuthClient(ABC):
    def __init__(self, config: OAuthConfig, provider: OAuthProvider):
        self.config = config
        self.provider = provider
        self.client = AsyncClient()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.client.aclose()

    async def _send(self, request: Awaitable[Response]) -> Response:
        """vendor HTTP 호출 + httpx 예외를 도메인 예외로 변환.

        4xx → OAuthInvalidGrantError(400), 5xx·네트워크 → OAuthVendorError(502).
        예외 메시지에 PII·vendor 본문을 싣지 않는다.
        """
        try:
            response = await request
            response.raise_for_status()
        except HTTPStatusError as e:
            if e.response.status_code >= 500:
                raise OAuthVendorError(_VENDOR_ERROR_MESSAGE) from e
            raise OAuthInvalidGrantError(_INVALID_GRANT_MESSAGE) from e
        except RequestError as e:
            raise OAuthVendorError(_VENDOR_ERROR_MESSAGE) from e
        return response

    def get_authorization_url(self, state: str, user_type: str) -> str:
        params = {
            "client_id": self.config.client_id,
            "redirect_uri": f"{self.config.redirect_uri}/{user_type}",
            "response_type": "code",
            "state": state,
        }
        if self.config.scope:
            params["scope"] = self.config.scope
        
        # 로그인 캐쉬 안 되게 수정
        if self.provider == OAuthProvider.GOOGLE:
            params["prompt"] = "select_account"
        
        query_string = urlencode(params)
        return f"{self.config.authorize_url}?{query_string}"
    
    async def get_access_token(self, code: str, user_type: str) -> str:
        data = {
            "grant_type": "authorization_code",
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "redirect_uri": f"{self.config.redirect_uri}/{user_type}",
            "code": code,
        }
        
        response = await self._send(self.client.post(
            self.config.token_url,
            data=data,
            headers={"Accept": "application/json"}
        ))

        token_data = response.json()
        access_token = token_data.get("access_token")
        
        if not access_token:
            raise OAuthInvalidGrantError(_INVALID_GRANT_MESSAGE)
        return access_token
    
    @abstractmethod
    async def get_user_info(self, access_token: str) -> OAuthUser:
        pass