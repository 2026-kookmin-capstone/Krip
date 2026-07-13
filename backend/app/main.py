import asyncio
import os
import random
from contextlib import AsyncExitStack, asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import start_http_server

import app.database.model  # ORM relationship registry side effect
from app.api.v1.health import router as health_router
from app.api.v1.router import api_router
from app.config.setting import settings
from app.container import Container
from app.core.ai.menu_ocr.load import MenuOcr
from app.core.ai.papago_translator.load import PapagoTranslator
from app.core.ai.tour_planner.load import TourPlanner
from app.core.background_tasks import background_tasks
from app.core.chat.lua_script import lua_scripts
from app.core.fcm import close_fcm, init_fcm
from app.core.instrumentation import (
    attach_db_instrumentation,
    prime_worker_gauges,
    start_event_loop_monitor,
    stop_event_loop_monitor,
)
from app.core.logger import get_logger, setup_logging
from app.core.metric import build_instrumentator
from app.core.redis import close_redis, get_redis_client, get_redis_dedupe_client
from app.database.session import close_mongodb, init_mongodb
from app.domain.auth.worker.withdraw_purge import (
    start_withdraw_purge_scheduler,
    stop_withdraw_purge_scheduler,
)
from app.domain.chat.worker.fanout_dispatcher import (
    start_fanout_dispatcher,
    stop_fanout_dispatcher,
)
from app.domain.chat.worker.node_registry import (
    start_node_registry,
    stop_node_registry,
)
from app.domain.chat.worker.reconcile import (
    start_reconcile_scheduler,
    stop_reconcile_scheduler,
)
from app.middleware.auth import BearerTokenMiddleware, LoginAuthMiddleware, RegisterCheckMiddleware
from app.middleware.tracking import (
    ErrorTrackingMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
)


logger = get_logger("main")


async def _stop_metrics_server(server, thread) -> None:
    """Prometheus WSGI server를 event loop를 막지 않고 종료한다."""
    def stop() -> None:
        try:
            server.shutdown()
        finally:
            try:
                server.server_close()
            finally:
                thread.join()

    await asyncio.to_thread(stop)


def create_app() -> FastAPI:
    """FastAPI 애플리케이션 팩토리"""
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with AsyncExitStack() as stack:
            setup_logging()

            # handle을 보존해 startup rollback과 shutdown 모두에서 metrics socket을 닫는다.
            metrics_server, metrics_thread = start_http_server(settings.METRICS_PORT)
            stack.push_async_callback(
                _stop_metrics_server, metrics_server, metrics_thread,
            )
            logger.info("Prometheus /metrics on :{}", settings.METRICS_PORT)

            # 첫 tick 전 WorkerStale 오탐을 막는다.
            prime_worker_gauges()

            # Container singleton engine은 instrumentation 전에 이미 생성된다.
            engine = app.container.engine()
            stack.push_async_callback(engine.dispose)
            lock_engine = app.container.image_reference_lock_engine()
            stack.push_async_callback(lock_engine.dispose)
            # instrumentation이 전역 pool state를 일부 설정한 뒤 실패해도 초기화한다.
            stack.push_async_callback(stop_event_loop_monitor)
            attach_db_instrumentation(engine)

            start_event_loop_monitor()

            random.seed(int.from_bytes(os.urandom(16), "big"))

            # index 초기화 실패 전 생성된 client도 rollback한다.
            stack.push_async_callback(close_mongodb)
            await init_mongodb()

            stack.push_async_callback(close_redis)
            hot_redis = await get_redis_client()
            await get_redis_dedupe_client()
            lua_scripts.load(hot_redis)

            stack.callback(close_fcm)
            init_fcm()

            stack.push_async_callback(stop_reconcile_scheduler)
            start_reconcile_scheduler(app.container.session_factory())

            # SUBSCRIBE 후 registry 등록, 종료는 LIFO로 역순을 보장한다.
            stack.push_async_callback(stop_fanout_dispatcher)
            await start_fanout_dispatcher(app.container.fanout_service())
            stack.push_async_callback(stop_node_registry)
            await start_node_registry()

            stack.push_async_callback(stop_withdraw_purge_scheduler)
            start_withdraw_purge_scheduler(app.container.session_factory())

            MenuOcr().load()
            papago = PapagoTranslator()
            stack.push_async_callback(papago.close)
            papago.load()
            await TourPlanner().load()

            background_tasks.start()
            # shutdown 첫 단계에서 admission을 닫고 drain한 뒤 shared resource를 해제한다.
            stack.push_async_callback(background_tasks.stop)
            logger.info("Application started in {} mode", settings.ENVIRONMENT)

            yield

        logger.info("Application shut down")

    container = Container()
    container.wire(modules=[
        "app.domain.auth.router.login",
        "app.domain.auth.router.app_login",
        "app.domain.auth.router.register",
        "app.domain.auth.router.profile",
        "app.domain.auth.router.withdraw",
        "app.domain.tripmate.router.tripmate_post",
        "app.domain.tripmate.router.tripmate_search_history",
        "app.domain.tripmate.router.tripmate_image",
        "app.domain.menu_ai.router.menu_ocr",
        "app.domain.translation.router.translation",
        "app.domain.tour.router.place",
        "app.domain.tour.router.recommend",
        "app.domain.tour.router.tour_search_history",
        "app.domain.tour.router.tour_plan",
        "app.domain.friend.router.friendship",
        "app.domain.friend.router.user_block",
        "app.domain.friend.router.detail",
        "app.domain.friend.router.search",
        "app.domain.friend.router.search_history",
        "app.domain.chat.router.room",
        "app.domain.chat.router.message",
        "app.domain.chat.router.ws",
        "app.domain.public.router.share",
        "app.domain.notification.router.fcm_token",
        "app.domain.notification.router.mute",
        "app.domain.notification.router.inbox",
        "app.domain.feed.router.feed_post",
        "app.domain.feed.router.feed_user",
        "app.domain.feed.router.feed_post_like",
        "app.domain.feed.router.feed_post_comment",
        "app.domain.feed.router.feed_popup",
    ])

    # PROD에서는 API 명세 라우트를 등록하지 않는다.
    app = FastAPI(
        title="Krip API",
        description="Krip 서버",
        version="0.3.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )

    # Starlette middleware는 등록 역순으로 실행된다.
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RegisterCheckMiddleware)
    app.add_middleware(LoginAuthMiddleware)
    app.add_middleware(BearerTokenMiddleware)
    app.add_middleware(ErrorTrackingMiddleware)
    app.add_middleware(RequestIDMiddleware)

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

    # 가장 바깥쪽에서 인증 실패까지 계측한다. /metrics는 별도 포트에서 노출한다.
    build_instrumentator().instrument(app)

    app.include_router(api_router)

    # 인프라 probe용이라 `/api` prefix를 적용하지 않는다.
    app.include_router(health_router)

    # DEV Swagger에만 middleware 인증 scheme을 노출한다.
    if not settings.is_production:
        _default_openapi = app.openapi

        def _openapi_with_bearer():
            schema = _default_openapi()
            schema.setdefault("components", {}).setdefault("securitySchemes", {})["BearerAuth"] = {
                "type": "http",
                "scheme": "bearer",
                "description": "settings.ACCESS_TOKEN 값을 입력. DEV 환경에서만 노출.",
            }
            schema["security"] = [{"BearerAuth": []}]
            return schema

        app.openapi = _openapi_with_bearer

    app.container = container

    return app
    
    
app = create_app()


if __name__ == "__main__":
    # reload=True는 app 객체가 아닌 import 문자열을 요구한다.
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=not settings.is_production,
        log_config=None,
    )