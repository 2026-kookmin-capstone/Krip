import hmac
from typing import Callable, Sequence
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
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
        # "/api/auth/cookie-test",
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
