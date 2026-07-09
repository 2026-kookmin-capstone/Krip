from abc import ABC, abstractmethod
from typing import Optional
from urllib.parse import urlencode

from httpx import AsyncClient

from app.config.oauth import OAuthConfig, OAuthProvider


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
        
        response = await self.client.post(
            self.config.token_url,
            data=data,
            headers={"Accept": "application/json"}
        )
        response.raise_for_status()
        
        token_data = response.json()
        return token_data.get("access_token")
    
    @abstractmethod
    async def get_user_info(self, access_token: str) -> OAuthUser:
        pass