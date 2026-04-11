from typing import Callable, Sequence
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import jwt
import hmac
from fastapi import Request, Response
from fastapi.responses import JSONResponse

from app.core.redis import RedisClient
from app.core.logger import get_logger
from app.core.cache.redis_cache import get_redis_cache_manager
from app.core.cache.key_category import KeyCategory
from app.config.setting import settings


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
        cookie_logger.debug("쿠키 인증 성공: %s", user_id)
        return await call_next(request)


class RegisterCheckMiddleware(BaseHTTPMiddleware):
    """2차 회원가입 완료 여부 검증 미들웨어

    user_id로 2차 회원가입 완료 여부를 확인한다.
    Redis 캐시를 우선 조회하고, 캐시 미스 시 DB를 조회하여 결과를 캐싱한다.
    """

    REDIS_KEY_PREFIX = KeyCategory.REGISTERED
    CACHE_TTL = RedisClient.DEFAULT_CACHE_TTL  # 24시간

    # 검증을 건너뛸 경로
    EXCLUDE_PATHS: Sequence[str] = (
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
    )

    # 검증을 건너뛸 경로 prefix (로그인, 회원가입, 로그아웃)
    EXCLUDE_PREFIXES: Sequence[str] = (
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/logout",
    )


    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.logger = get_logger("middleware.register_check")


    def _is_excluded(self, path: str) -> bool:
        """검증 제외 대상 경로인지 확인"""
        if path in self.EXCLUDE_PATHS:
            return True
        return any(path.startswith(prefix) for prefix in self.EXCLUDE_PREFIXES)


    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if self._is_excluded(request.url.path):
            return await call_next(request)

        user_id = getattr(request.state, "user_id", None)
        if user_id is None:
            return await call_next(request)

        request_id = getattr(request.state, "request_id", "unknown")
        reg_logger = self.logger.bind(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            user_id=user_id,
        )

        # 1. Redis 캐시 조회
        cache = get_redis_cache_manager()
        cache_key = f"{self.REDIS_KEY_PREFIX}:{user_id}"

        if await cache.exists(cache_key):
            reg_logger.debug("2차 회원가입 캐시 히트")
            return await call_next(request)

        # 2. DB 조회 (캐시 미스) — 유저 존재 + 2차 회원가입 완료 여부를 한 번에 확인
        try:
            container = request.app.container
            async with container.uow() as session:
                from app.domain.auth.repository.user_repository import UserRepository
                user_repo = UserRepository(session)
                user = await user_repo.find_by_id_with_profile(user_id)
        except Exception as e:
            reg_logger.error("DB 조회 실패: %s", e)
            return JSONResponse(
                status_code=500,
                content={"detail": "회원가입 상태 확인 중 오류가 발생했습니다."},
            )

        if user is None:
            reg_logger.warning("존재하지 않는 유저")
            return JSONResponse(
                status_code=401,
                content={"detail": "존재하지 않는 유저입니다."},
            )

        if user.detail is None:
            reg_logger.warning("2차 회원가입 미완료")
            return JSONResponse(
                status_code=403,
                content={"detail": "2차 회원가입이 필요합니다."},
            )

        # 3. Redis 캐시 저장
        await cache.set_flag(cache_key, self.CACHE_TTL)

        return await call_next(request)
