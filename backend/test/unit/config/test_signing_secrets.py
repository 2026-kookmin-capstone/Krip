"""Settings._validate_signing_secrets — JWT 서명키 검증 단위 테스트.

PROD 기동 시 취약/기본 서명키면 하드 실패, 비-PROD 는 로컬 개발 편의상 허용.
필수 필드(ACCESS_TOKEN 등)는 테스트 env 에서 로드하고 JWT/ENVIRONMENT 만 override 한다.
"""
import pytest
from pydantic import ValidationError

from app.config.setting import Settings


pytestmark = pytest.mark.unit

_STRONG = "x" * 40
_PLACEHOLDER = "your-secret-key-here"


class TestSigningSecretValidation:
    def test_prod_placeholder_raises(self):
        with pytest.raises(ValidationError):
            Settings(
                ENVIRONMENT="PROD",
                USER_LOGIN_JWT_SECRET_KEY=_PLACEHOLDER,
                SHARE_JWT_SECRET_KEY=_STRONG,
            )

    def test_prod_short_secret_raises(self):
        with pytest.raises(ValidationError):
            Settings(
                ENVIRONMENT="PROD",
                USER_LOGIN_JWT_SECRET_KEY="short",
                SHARE_JWT_SECRET_KEY=_STRONG,
            )

    def test_prod_strong_secrets_ok(self):
        Settings(
            ENVIRONMENT="PROD",
            USER_LOGIN_JWT_SECRET_KEY=_STRONG,
            SHARE_JWT_SECRET_KEY=_STRONG,
        )

    def test_non_prod_placeholder_allowed(self):
        # 하드 실패는 PROD 한정 — 비-PROD 는 기본키로도 기동 (로컬 개발 편의).
        Settings(
            ENVIRONMENT="DEV",
            USER_LOGIN_JWT_SECRET_KEY=_PLACEHOLDER,
            SHARE_JWT_SECRET_KEY=_STRONG,
        )
