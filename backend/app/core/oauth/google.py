from app.config.oauth import OAuthConfig, OAuthProvider
from app.core.oauth.base import OAuthClient, OAuthUser


class GoogleOAuthClient(OAuthClient):
    def __init__(self, config: OAuthConfig):
        super().__init__(config, OAuthProvider.GOOGLE)
    
    async def get_user_info(self, access_token: str) -> OAuthUser:
        response = await self.client.get(
            self.config.userinfo_url,
            headers={"Authorization": f"Bearer {access_token}"}
        )
        response.raise_for_status()
        
        user_data = response.json()
        return OAuthUser(
            email=user_data["email"],
            provider=self.provider,
            name=user_data.get("name")
        )