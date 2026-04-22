import os
import random
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.middleware.tracking import (
    RequestIDMiddleware,
    ErrorTrackingMiddleware,
    SecurityHeadersMiddleware,
)
from app.middleware.auth import BearerTokenMiddleware, LoginCookieMiddleware, RegisterCheckMiddleware
import app.database.model # Relation Lazy Load 문제 해결하기 위한 import!
from app.core.ai.tour_planner.load import TourPlanner
from app.core.logger import setup_logging, get_logger
from app.core.ai.menu_ocr.load import MenuOcr
from app.core.redis import get_redis_client, get_redis_dedupe_client, close_redis
from app.container import Container
from app.config.setting import settings
from app.database.session import init_mongodb, close_mongodb
from app.core.chat.lua_script import lua_scripts
from app.api.v1.router import api_router


logger = get_logger("main")


def create_app() -> FastAPI:
    """FastAPI 애플리케이션 팩토리"""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # startup
        setup_logging()

        # force_jump Lua 호출 시 사용할 jitter 엔트로피 보강 (PHASE_1.md §3)
        random.seed(int.from_bytes(os.urandom(16), "big"))

        await init_mongodb()

        # Redis 양쪽 DB 커넥션 pre-warm 후 hot 클라이언트에 Lua 스크립트 등록.
        hot_redis = await get_redis_client()
        await get_redis_dedupe_client()
        lua_scripts.load(hot_redis)

        MenuOcr().load()
        await TourPlanner().load()
        logger.info("Starting application in {} mode", settings.ENVIRONMENT)

        yield

        # shutdown
        await close_mongodb()
        await close_redis()
        logger.info("Application shutting down")

    # DI Container 초기화 및 wiring
    container = Container()
    container.wire(modules=[
        "app.domain.auth.router.login.login",
        "app.domain.auth.router.login.register",
        "app.domain.auth.router.profile.me",
        "app.domain.auth.router.withdraw",
        "app.domain.tripmate.router.tripmate_post",
        "app.domain.tripmate.router.tripmate_search_history",
        "app.domain.tripmate.router.tripmate_image",
        "app.domain.menu_ai.router.menu_ocr",
        "app.domain.tour.router.place",
        "app.domain.tour.router.tour_search_history",
        "app.domain.friend.router.friendship",
        "app.domain.friend.router.user_block",
        "app.domain.friend.router.detail",
        "app.domain.chat.router.room",
        "app.domain.chat.router.message",
        "app.domain.chat.router.ws",
    ])


    app = FastAPI(
        title="Krip API",
        description="Krip 서버",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # 미들웨어 (등록 역순으로 실행됨 → CORS가 가장 먼저 실행)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RegisterCheckMiddleware)
    app.add_middleware(LoginCookieMiddleware)
    app.add_middleware(BearerTokenMiddleware)
    app.add_middleware(ErrorTrackingMiddleware)
    app.add_middleware(RequestIDMiddleware)

    # CORS (가장 마지막에 등록 → 가장 바깥쪽에서 실행되어 모든 응답에 CORS 헤더 추가)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            settings.FRONTEND_URL,
            settings.LOCAL_FRONTEND_URL,
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 라우터
    app.include_router(api_router)
    
    app.container = container
    
    return app
    
    
app = create_app()


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=settings.HOST,
        port=settings.PORT,
        reload=not settings.is_production,
        log_config=None,
    )