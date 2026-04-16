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
from app.container import Container
from app.config.setting import settings
from app.database.session import init_mongodb, close_mongodb
from app.api.v1.router import api_router


logger = get_logger("main")


def create_app() -> FastAPI:
    """FastAPI 애플리케이션 팩토리"""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # startup
        setup_logging()
        await init_mongodb()
        MenuOcr().load()
        await TourPlanner().load()
        logger.info("Starting application in {} mode", settings.ENVIRONMENT)

        yield

        # shutdown
        await close_mongodb()
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