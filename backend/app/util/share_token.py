"""플랜 공유 토큰 (JWT) 발급/검증 유틸.

발급 측 (TourPlanService) 과 검증 측 (SharePlanService) 이 공유하는 단일 진실 소스.
서명 알고리즘 / 비밀키 / 만료 정책은 모두 settings 로 중앙화.
"""
from datetime import datetime, timedelta, timezone
from typing import Tuple

import jwt

from app.config.setting import settings


class ShareTokenError(ValueError):
    """공유 토큰이 무효하거나 만료됨 — Router 에서 400 으로 매핑."""


def encode_share_token(plan_id: str) -> Tuple[str, datetime]:
    """plan_id 로 JWT 공유 토큰 발급.

    Returns:
        (token, expires_at) — token 은 HS256 서명, expires_at 은 timezone-aware UTC.
    """
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.SHARE_JWT_EXPIRATION_DAYS)
    payload = {
        "plan_id": plan_id,
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(
        payload,
        settings.SHARE_JWT_SECRET_KEY,
        algorithm=settings.SHARE_JWT_ALGORITHM,
    )
    return token, expires_at


def decode_share_token(token: str) -> str:
    """공유 토큰 디코드 → plan_id 반환.

    Raises:
        ShareTokenError: 만료, 서명 불일치, payload 손상 등 모든 무효 케이스.
    """
    try:
        payload = jwt.decode(
            token,
            settings.SHARE_JWT_SECRET_KEY,
            algorithms=[settings.SHARE_JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError:
        raise ShareTokenError("공유 토큰이 만료되었습니다.")
    except jwt.InvalidTokenError:
        raise ShareTokenError("유효하지 않은 공유 토큰입니다.")

    plan_id = payload.get("plan_id")
    if not isinstance(plan_id, str) or not plan_id:
        raise ShareTokenError("유효하지 않은 공유 토큰입니다.")
    return plan_id
