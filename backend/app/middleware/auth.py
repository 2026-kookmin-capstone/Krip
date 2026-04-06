from typing import Callable, Sequence
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import jwt
import hmac
from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.config.setting import settings
from app.core.logger import get_logger


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Bearer 토큰 인증 미들웨어

    Authorization 헤더에서 Bearer 토큰을 검증하여
    settings.ACCESS_TOKEN과 일치하지 않으면 401 응답을 반환한다.
    """

    # 인증을 건너뛸 경로
    EXCLUDE_PATHS: Sequence[str] = (
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    )

    # 인증을 건너뛸 경로 prefix
    EXCLUDE_PREFIXES: Sequence[str] = (
        "/api/auth/login",
    )


    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.logger = get_logger("middleware.auth")


    def _is_excluded(self, path: str) -> bool:
        """인증 제외 대상 경로인지 확인"""
        if path in self.EXCLUDE_PATHS:
            return True
        return any(path.startswith(prefix) for prefix in self.EXCLUDE_PREFIXES)


    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if self._is_excluded(request.url.path):
            return await call_next(request)

        request_id = getattr(request.state, "request_id", "unknown")
        auth_logger = self.logger.bind(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        # Authorization 헤더 확인
        authorization = request.headers.get("Authorization")
        if not authorization:
            auth_logger.warning("Authorization 헤더 없음")
            return JSONResponse(
                status_code=401,
                content={"detail": "Authorization 헤더가 필요합니다"},
            )

        # Bearer 형식 확인
        parts = authorization.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            auth_logger.warning("잘못된 Authorization 형식")
            return JSONResponse(
                status_code=401,
                content={"detail": "Bearer 토큰 형식이 올바르지 않습니다"},
            )

        token = parts[1]

        # 토큰 검증 (타이밍 공격 방지)
        if not hmac.compare_digest(token, settings.ACCESS_TOKEN):
            auth_logger.warning("유효하지 않은 Bearer Token 토큰")
            return JSONResponse(
                status_code=401,
                content={"detail": "유효하지 않은 토큰입니다"},
            )

        auth_logger.debug("토큰 인증 성공")
        return await call_next(request)


class LoginCookieMiddleware(BaseHTTPMiddleware):
    """로그인 쿠키 인증 미들웨어

    JWT 로그인 쿠키를 검증하여 user_id를 request.state.user_id에 저장한다.
    쿠키가 필요 없는 경로(로그인, docs 등)는 건너뛴다.
    """

    # 쿠키 검증을 건너뛸 경로
    EXCLUDE_PATHS: Sequence[str] = (
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    )

    # 쿠키 검증을 건너뛸 경로 prefix
    EXCLUDE_PREFIXES: Sequence[str] = (
        "/api/auth/login",
    )


    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.logger = get_logger("middleware.cookie_auth")


    def _is_excluded(self, path: str) -> bool:
        """인증 제외 대상 경로인지 확인"""
        if path in self.EXCLUDE_PATHS:
            return True
        return any(path.startswith(prefix) for prefix in self.EXCLUDE_PREFIXES)


    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if self._is_excluded(request.url.path):
            return await call_next(request)

        request_id = getattr(request.state, "request_id", "unknown")
        cookie_logger = self.logger.bind(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        token = request.cookies.get(settings.USER_LOGIN_COOKIE_NAME)
        if token is None:
            cookie_logger.warning("로그인 쿠키 없음")
            return JSONResponse(
                status_code=401,
                content={"detail": "로그인 쿠키가 없습니다."},
            )

        try:
            payload = jwt.decode(
                token,
                settings.USER_LOGIN_JWT_SECRET_KEY,
                algorithms=[settings.USER_LOGIN_JWT_ALGORITHM],
            )
            user_id = payload.get("user_id")
            if user_id is None:
                cookie_logger.warning("쿠키에 user_id 없음")
                return JSONResponse(
                    status_code=401,
                    content={"detail": "유효하지 않은 토큰입니다."},
                )
        except jwt.ExpiredSignatureError:
            cookie_logger.warning("로그인 쿠키 만료")
            return JSONResponse(
                status_code=401,
                content={"detail": "토큰이 만료되었습니다."},
            )
        except jwt.InvalidTokenError:
            cookie_logger.warning("유효하지 않은 로그인 쿠키")
            return JSONResponse(
                status_code=401,
                content={"detail": "유효하지 않은 토큰입니다."},
            )

        request.state.user_id = user_id
        cookie_logger.debug(f"쿠키 인증 성공: {user_id}")
        return await call_next(request)
