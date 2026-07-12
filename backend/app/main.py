import asyncio
import os
import random
from contextlib import AsyncExitStack, asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import start_http_server

import app.database.model  # Relation Lazy Load 문제 해결하기 위한 import!
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

            # /metrics 를 별도 포트로 노출한다. 반환 handle을 보존해 rollback과 정상
            # shutdown 모두에서 thread와 listening socket을 닫는다.
            metrics_server, metrics_thread = start_http_server(settings.METRICS_PORT)
            stack.push_async_callback(
                _stop_metrics_server, metrics_server, metrics_thread,
            )
            logger.info("Prometheus /metrics on :{}", settings.METRICS_PORT)

            # 워커 last_tick_timestamp 를 startup 시각으로 priming.
            # 첫 tick 전까지 false-negative WorkerStale 알람이 발생하지 않도록 한다.
            prime_worker_gauges()

            # Container singleton engine은 instrumentation 전에 이미 생성된다.
            engine = app.container.engine()
            stack.push_async_callback(engine.dispose)
            # instrumentation이 pool 참조 설정 뒤 실패해도 전역 참조를 reset한다.
            stack.push_async_callback(stop_event_loop_monitor)
            attach_db_instrumentation(engine)

            start_event_loop_monitor()

            # force_jump Lua 호출 시 사용할 jitter 엔트로피 보강
            random.seed(int.from_bytes(os.urandom(16), "big"))

            # connect가 client를 먼저 할당한 뒤 index 초기화에서 실패할 수 있다.
            stack.push_async_callback(close_mongodb)
            await init_mongodb()

            # hot client 성공 후 dedupe pre-warm가 실패해도 양쪽을 닫는다.
            stack.push_async_callback(close_redis)
            hot_redis = await get_redis_client()
            await get_redis_dedupe_client()
            lua_scripts.load(hot_redis)

            stack.callback(close_fcm)
            init_fcm()

            stack.push_async_callback(stop_reconcile_scheduler)
            start_reconcile_scheduler(app.container.session_factory())

            # dispatcher SUBSCRIBE 후 registry 등록 순서를 유지한다. stack의 LIFO 종료는
            # registry 제거 후 dispatcher unsubscribe 순서를 자동으로 보장한다.
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
            # 마지막에 등록해 shutdown 첫 단계에서 admission을 닫고 drain한다. FCM/Redis/
            # Mongo/SQL teardown은 background task가 종료된 뒤 LIFO 순서로 진행된다.
            stack.push_async_callback(background_tasks.stop)
            logger.info("Application started in {} mode", settings.ENVIRONMENT)

            yield

        logger.info("Application shut down")

    # DI Container 초기화 및 wiring
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

    # PROD 에서는 Swagger / ReDoc / OpenAPI 스키마를 모두 비활성화하여 API 명세 노출을 차단.
    # docs_url=None 이면 FastAPI 가 해당 라우트를 등록하지 않아 404 반환된다.
    # openapi_url=None 시 Swagger 도 동작 불가하므로 셋이 함께 토글된다.
    app = FastAPI(
        title="Krip API",
        description="Krip 서버",
        version="0.3.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )

    # 미들웨어 (등록 역순으로 실행됨 → CORS가 가장 먼저 실행)
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RegisterCheckMiddleware)
    app.add_middleware(LoginAuthMiddleware)
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

    # 메트릭 계측은 모든 미들웨어 등록 이후에 부착한다.
    # Starlette 의 add_middleware 는 LIFO 라 마지막에 등록된 것이 가장 바깥쪽에 위치한다.
    # 그래야 인증 실패로 401, 403, 419 가 반환되는 요청까지 RED 메트릭에 잡힌다.
    # instrument(app) 만 호출하고 expose(app) 는 호출하지 않는다.
    # /metrics 노출은 lifespan 의 start_http_server 가 별도 포트에서 처리한다.
    build_instrumentator().instrument(app)

    # 라우터
    app.include_router(api_router)

    # 헬스체크 — `/api` prefix 우회. k8s probe / Watchdog / blackbox 가 직접 `/health`, `/health/deep`, `/ready` 호출.
    app.include_router(health_router)

    # Swagger Authorize 버튼 (DEV 한정) — BearerTokenMiddleware 가 Starlette 미들웨어라
    # OpenAPI 스키마에 노출되지 않아 `/docs` 에서 토큰 입력 칸이 없다. securitySchemes 만
    # 얹어 Swagger UI 가 Authorize 버튼을 렌더하도록 한다. 실제 검증은 미들웨어가 그대로 수행.
    # PROD 에서는 패치하지 않아 명세 노출을 최소화한다.
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
    # 직접 실행할 경우, reload=True 는 app 객체가 아닌 import 문자열을 요구한다. 
    # 객체를 넘기면 uvicorn 이 경고 후 sys.exit(1) 로 종료돼 서버가 뜨지 않는다.
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=not settings.is_production,
        log_config=None,
    )