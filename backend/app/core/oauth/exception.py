"""OAuth 코어 전용 예외 — vendor(httpx) 예외를 도메인 예외로 변환해 Router 가 매핑."""


class OAuthError(Exception):
    """OAuth 도메인 예외 베이스."""


class OAuthInvalidGrantError(OAuthError):
    """vendor 4xx(만료/재사용 code, access_token 누락) → Router 400."""


class OAuthVendorError(OAuthError):
    """vendor 5xx / 네트워크 오류 → Router 502."""
