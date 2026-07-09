from urllib.parse import urlencode
from typing import Optional
import jwt
from fastapi.responses import RedirectResponse
from fastapi import APIRouter, Query, HTTPException, Request, Depends
from dependency_injector.wiring import Provide, inject
from datetime import datetime, timedelta, timezone

from app.domain.auth.service.signup import SignupService
from app.core.oauth import OAUTH_CLIENTS
from app.core.logger import get_logger
from app.container import Container
from app.config.setting import settings
from app.config.oauth import OAuthProvider, OAUTH_CONFIGS
from app.util.oauth_state import (
    generate_state_nonce, set_state_cookie, verify_state_nonce, clear_state_cookie,
)


router = APIRouter(prefix="/login", tags=["로그인"])
logger = get_logger("auth.login")


@router.get("")
async def login(type: OAuthProvider = Query(..., description="OAuth 제공자 타입"), is_local: Optional[bool] = Query(None, description="로컬에서 로그인할 경우")):
    """OAuth 로그인 - 해당 제공자의 인증 페이지로 리다이렉트"""
    config = OAUTH_CONFIGS.get(type)
    if not config:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 OAuth 제공자: {type}")

    client_class = OAUTH_CLIENTS.get(type)
    if not client_class:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 OAuth 제공자: {type}")

    redirect_url = 'local' if is_local else 'server'

    nonce = generate_state_nonce()
    state = f"{redirect_url}:{type.value}:{nonce}"

    async with client_class(config) as client:
        authorization_url = client.get_authorization_url(state=state, user_type="callback")

    response = RedirectResponse(url=authorization_url)
    set_state_cookie(response, nonce)
    return response


@router.get("/callback")
@inject
async def login_callback(
    request: Request,
    code: str = Query(...), state: str = Query(...),
    signup_service: SignupService = Depends(Provide[Container.signup_service])
):
    """OAuth 콜백 - 인증 코드로 사용자 정보를 가져와 JWT 쿠키 발급"""
    parts = state.split(":")
    if len(parts) != 3:
        raise HTTPException(status_code=400, detail="잘못된 state 값")

    redirect_url, provider_value, nonce = parts
    verify_state_nonce(request, nonce)

    try:
        provider = OAuthProvider(provider_value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 OAuth 제공자: {provider_value}")

    config = OAUTH_CONFIGS[provider]
    client_class = OAUTH_CLIENTS.get(provider)
    
    if not client_class:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 OAuth 제공자: {provider}")

    async with client_class(config) as client:
        access_token = await client.get_access_token(code=code, user_type="callback")
        user_info = await client.get_user_info(access_token=access_token)

    # PII(email·실명) 는 로그에 남기지 않는다 — Promtail 수집 파이프라인에 개인정보 축적 방지.
    logger.info("OAuth 로그인 성공: provider={} provider_account_id={}", provider.value, user_info.id)
    
    result = await signup_service.check_and_register(
        auth_provider=provider.value,
        auth_provider_id=user_info.id,
    )

    redirect_to = settings.FRONTEND_URL if redirect_url == 'server' else settings.LOCAL_FRONTEND_URL

    params = {"status": result.status.value}
    if user_info.email:
        params["email"] = user_info.email
    if user_info.name:
        params["name"] = user_info.name

    response = RedirectResponse(url=f"{redirect_to}?{urlencode(params)}")

    # status 가 WITHDRAWAL_PENDING 이어도 쿠키는 발급한다 — 프론트가 status 또는 보호
    # 경로에서 받는 419 를 보고 /api/auth/withdraw/cancel 화면으로 라우팅. RegisterCheck
    # 미들웨어가 INACTIVE 유저의 보호 경로 진입을 419 로 차단하므로 보안상 문제 없음.
    payload = {
        "user_id": result.user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=settings.USER_LOGIN_JWT_EXPIRATION_DAYS),
        "iat": datetime.now(timezone.utc),
    }
    token = jwt.encode(payload, settings.USER_LOGIN_JWT_SECRET_KEY, algorithm=settings.USER_LOGIN_JWT_ALGORITHM)

    response.set_cookie(
        key=settings.USER_LOGIN_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="none", # 개발 단계 추후, None -> lax
        path="/",
        max_age=settings.USER_LOGIN_JWT_EXPIRATION_DAYS * 24 * 60 * 60,
    )
    clear_state_cookie(response)

    return response