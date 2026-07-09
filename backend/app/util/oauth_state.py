"""OAuth state CSRF 방어 — 흐름별 두 전략.

웹(login.py): nonce 를 `state` + HttpOnly 쿠키에 실어 콜백에서 대조하는 double-submit(브라우저 바인딩).

앱(app_login.py): 인앱 브라우저 쿠키 왕복이 실기기에서 보장되지 않아(fail-closed 위험),
nonce 를 Redis 에 단발성(TTL + 1회용)으로 저장한다. 최종 CSRF 경계는 `krip://` 딥링크
스킴 등록(OS 가 정당한 앱에만 콜백 전달)이 보완한다.
"""
import hmac
import secrets

from fastapi import HTTPException, Request
from starlette.responses import Response

from app.core.redis import get_redis_client


STATE_COOKIE_NAME = "oauth_state"
_STATE_COOKIE_PATH = "/api/auth/login"
_STATE_TTL_SECONDS = 600  # 로그인 시작 → 콜백 왕복 여유 (10분)
_STATE_REDIS_PREFIX = "oauth_state:"


def generate_state_nonce() -> str:
    return secrets.token_urlsafe(32)


def set_state_cookie(response: Response, nonce: str) -> None:
    """로그인 시작 응답(→ provider redirect)에 nonce 쿠키를 심는다.

    SameSite=Lax — provider 에서 돌아오는 콜백은 top-level GET 이라 Lax 로 전송된다.
    """
    response.set_cookie(
        key=STATE_COOKIE_NAME,
        value=nonce,
        httponly=True,
        secure=True,
        samesite="lax",
        path=_STATE_COOKIE_PATH,
        max_age=_STATE_TTL_SECONDS,
    )


def verify_state_nonce(request: Request, nonce: str) -> None:
    """콜백에서 state 의 nonce 와 쿠키 값을 상수시간 비교. 불일치/부재 시 400."""
    cookie = request.cookies.get(STATE_COOKIE_NAME)
    if not cookie or not nonce or not hmac.compare_digest(cookie, nonce):
        raise HTTPException(status_code=400, detail="유효하지 않은 OAuth state 입니다.")


def clear_state_cookie(response: Response) -> None:
    """검증 후 nonce 쿠키 제거 (1회용)."""
    response.delete_cookie(STATE_COOKIE_NAME, path=_STATE_COOKIE_PATH)


# ──────────────────── 앱 흐름 — Redis 단발성 nonce (쿠키 비의존) ────────────────────

async def store_state_nonce() -> str:
    """앱 로그인 시작 — 단발성 nonce 를 생성해 Redis 에 TTL 로 저장하고 반환."""
    nonce = generate_state_nonce()
    redis = await get_redis_client()
    await redis.set(f"{_STATE_REDIS_PREFIX}{nonce}", "1", ex=_STATE_TTL_SECONDS)
    return nonce


async def consume_state_nonce(nonce: str) -> None:
    """앱 콜백 — nonce 를 원자적으로 1회 소비. 부재(위조)/만료/재사용이면 400.

    DELETE 반환값으로 존재 여부를 판정하므로 같은 nonce 재사용(replay)은 두 번째부터 거부된다.
    """
    if not nonce:
        raise HTTPException(status_code=400, detail="유효하지 않은 OAuth state 입니다.")
    redis = await get_redis_client()
    consumed = await redis.delete(f"{_STATE_REDIS_PREFIX}{nonce}")
    if not consumed:
        raise HTTPException(status_code=400, detail="유효하지 않은 OAuth state 입니다.")
