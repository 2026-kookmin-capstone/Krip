import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.middleware.tracking import (
    RequestIDMiddleware,
    ErrorTrackingMiddleware,
    SecurityHeadersMiddleware,
)
from app.middleware.auth import BearerTokenMiddleware
import app.database.model # Relation Lazy Load 문제 해결하기 위한 import! 
from app.core.logger import setup_logging, get_logger                                        
from app.config.setting import settings
from app.container import Container
from app.api.v1.router import api_router



logger = get_logger("main")


def create_app() -> FastAPI:
    """FastAPI 애플리케이션 팩토리"""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # startup
        setup_logging()
        logger.info(f"Starting application in {settings.ENVIRONMENT} mode")
        
        yield
        
        # shutdown
        logger.info("Application shutting down")

    # DI Container 초기화 및 wiring
    container = Container()
    container.wire(modules=[
        "app.domain.auth.router.login.login",
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

    # CORS
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

    # 미들웨어 (등록 역순으로 실행됨 → RequestID가 가장 먼저 실행)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(BearerTokenMiddleware)
    app.add_middleware(ErrorTrackingMiddleware)
    app.add_middleware(RequestIDMiddleware)

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