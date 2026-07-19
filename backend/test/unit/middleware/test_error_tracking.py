import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from loguru import logger
from pydantic import BaseModel

from app.api.v1 import health
from app.config.setting import settings
from app.main import create_app
from app.middleware.auth import BearerTokenMiddleware
from app.middleware.tracking import (
    ErrorTrackingMiddleware,
    RequestIDMiddleware,
    SecurityHeadersMiddleware,
    UnhandledExceptionMiddleware,
    _validation_error_summary,
    handle_validation_error,
)


async def _unused_app(scope, receive, send):
    raise AssertionError("middleware app should not be called directly")


def _respond(status_code, content):
    async def call_next(_request):
        return JSONResponse(status_code=status_code, content=content)

    return call_next


def _client_errors(records):
    return [
        record for record in records
        if record["extra"].get("event") == "http_client_error"
    ]


def _server_errors(records):
    return [
        record for record in records
        if record["extra"].get("event") == "http_server_error"
    ]


def _success_events(records):
    return [
        record for record in records
        if record["extra"].get("event") == "http_success"
    ]


def _assert_client_error(record, expected_extra):
    assert record["level"].name == "WARNING"
    assert record["message"] == "HTTP client error response"
    assert record["extra"] == {
        "logger_name": "middleware.error_tracking",
        "event": "http_client_error",
        **expected_extra,
    }


def _assert_server_error(record, expected_extra):
    assert record["level"].name == "ERROR"
    assert record["message"] == "HTTP server error response"
    assert record["extra"] == {
        "logger_name": "middleware.error_tracking",
        "event": "http_server_error",
        "error_app_location": None,
        "error_app_line": None,
        "error_cause": None,
        **expected_extra,
    }


@pytest.fixture
def log_records():
    records = []
    sink_id = logger.add(lambda message: records.append(message.record), level="DEBUG")
    try:
        yield records
    finally:
        logger.remove(sink_id)


def test_replaces_untrusted_client_request_id(log_records):
    app = FastAPI()

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    app.add_middleware(RequestIDMiddleware, generator=lambda: "RID_GENERATED")

    response = TestClient(app).get(
        "/ok",
        headers={"X-Request-ID": "PRIVATE_CLIENT_SUPPLIED_VALUE"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "RID_GENERATED"
    assert "PRIVATE_CLIENT_SUPPLIED_VALUE" not in repr(log_records)


def test_preserves_valid_uuid_request_id():
    request_id = "123e4567-e89b-12d3-a456-426614174000"
    app = FastAPI()

    @app.get("/ok")
    async def ok():
        return {"ok": True}

    app.add_middleware(RequestIDMiddleware, generator=lambda: "RID_GENERATED")

    response = TestClient(app).get("/ok", headers={"X-Request-ID": request_id})

    assert response.headers["X-Request-ID"] == request_id


async def test_logs_client_error_once_with_consistent_request_context(log_records):
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/items/ITEM_1",
        "query_string": b"secret=value",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "scheme": "http",
        "server": ("testserver", 80),
        "state": {"request_id": "RID_1", "user_id": "USER_1"},
        "route": SimpleNamespace(path="/api/items/{item_id}"),
    })
    middleware = ErrorTrackingMiddleware(_unused_app)

    response = await middleware.dispatch(
        request,
        _respond(404, {"detail": "not found"}),
    )

    client_errors = _client_errors(log_records)
    assert response.status_code == 404
    assert len(client_errors) == 1
    _assert_client_error(client_errors[0], {
        "request_id": "RID_1",
        "method": "GET",
        "path": "/api/items/{item_id}",
        "route": "/api/items/{item_id}",
        "status_code": 404,
        "user_id": "USER_1",
    })


async def test_logs_returned_server_error_once_with_consistent_request_context(log_records):
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/items/ITEM_1",
        "query_string": b"secret=value",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "scheme": "http",
        "server": ("testserver", 80),
        "state": {"request_id": "RID_500", "user_id": "USER_1"},
        "route": SimpleNamespace(path="/api/items/{item_id}"),
    })
    middleware = ErrorTrackingMiddleware(_unused_app)

    response = await middleware.dispatch(request, _respond(503, {"detail": "secret"}))

    server_errors = _server_errors(log_records)
    assert response.status_code == 503
    assert len(server_errors) == 1
    assert "secret" not in repr(server_errors)
    _assert_server_error(server_errors[0], {
        "request_id": "RID_500",
        "method": "POST",
        "path": "/api/items/{item_id}",
        "route": "/api/items/{item_id}",
        "status_code": 503,
        "user_id": "USER_1",
        "error_type": None,
        "error_location": None,
        "error_line": None,
    })


def test_logs_http_exception_server_error_once(log_records):
    app = FastAPI()

    @app.get("/vendor")
    async def vendor_failure():
        raise HTTPException(status_code=502, detail="PRIVATE_VENDOR_BODY")

    app.add_middleware(ErrorTrackingMiddleware)
    app.add_middleware(RequestIDMiddleware, generator=lambda: "RID_502")

    response = TestClient(app).get("/vendor")

    server_errors = _server_errors(log_records)
    assert response.status_code == 502
    assert len(server_errors) == 1
    assert "PRIVATE_VENDOR_BODY" not in repr(server_errors)
    _assert_server_error(server_errors[0], {
        "request_id": "RID_502",
        "method": "GET",
        "path": "/vendor",
        "route": "/vendor",
        "status_code": 502,
        "user_id": None,
        "error_type": None,
        "error_location": None,
        "error_line": None,
    })


def test_converts_unhandled_exception_to_safe_tracked_500(log_records):
    secret = "PRIVATE_EXCEPTION_MESSAGE"
    app = FastAPI()

    @app.get("/items/{item_id}")
    async def explode(item_id: str):
        raise RuntimeError(f"{secret}:{item_id}")

    app.add_middleware(ErrorTrackingMiddleware)
    app.add_middleware(RequestIDMiddleware, generator=lambda: "RID_RAISED")
    app.add_middleware(SecurityHeadersMiddleware)

    response = TestClient(app).get("/items/PRIVATE_ITEM")

    server_errors = _server_errors(log_records)
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal Server Error"}
    assert response.headers["X-Request-ID"] == "RID_RAISED"
    assert response.headers["X-Process-Time"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert len(server_errors) == 1
    assert secret not in repr(server_errors)
    assert "PRIVATE_ITEM" not in repr(server_errors)
    extra = server_errors[0]["extra"]
    assert extra["error_type"] == "RuntimeError"
    assert extra["error_location"].endswith(":explode")
    assert isinstance(extra["error_line"], int)
    # 라우트 함수가 테스트 모듈에 있어 가장 깊은 app.* 프레임은 미들웨어 자신이다.
    # 실제 앱에서는 도메인 코드가 더 깊어 그쪽이 잡힌다.
    assert extra["error_app_location"].startswith("app.middleware.")
    _assert_server_error(server_errors[0], {
        "request_id": "RID_RAISED",
        "method": "GET",
        "path": "/items/{item_id}",
        "route": "/items/{item_id}",
        "status_code": 500,
        "user_id": None,
        "error_type": "RuntimeError",
        "error_location": extra["error_location"],
        "error_line": extra["error_line"],
        "error_app_location": extra["error_app_location"],
        "error_app_line": extra["error_app_line"],
    })


def test_unhandled_500_preserves_cors_at_production_boundary(log_records):
    app = create_app()

    @app.get("/api/public/_test/cors-error")
    async def cors_error():
        raise RuntimeError("PRIVATE_CORS_EXCEPTION")

    response = TestClient(app).get(
        "/api/public/_test/cors-error",
        headers={"Origin": settings.LOCAL_FRONTEND_URL},
    )

    assert response.status_code == 500
    assert response.headers["Access-Control-Allow-Origin"] == settings.LOCAL_FRONTEND_URL
    exposed_headers = {
        header.strip().lower()
        for header in response.headers["Access-Control-Expose-Headers"].split(",")
    }
    assert exposed_headers == {"x-request-id", "x-process-time"}
    assert response.headers["X-Request-ID"]
    assert response.headers["X-Process-Time"]
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    server_errors = _server_errors(log_records)
    assert len(server_errors) == 1
    assert "PRIVATE_CORS_EXCEPTION" not in repr(server_errors)


def test_production_boundary_classifies_unmatched_404_and_returned_503_once(
    log_records,
):
    app = create_app()

    @app.get("/api/public/_test/returned-503")
    async def returned_503():
        return JSONResponse(status_code=503, content={"detail": "unavailable"})

    client = TestClient(app)
    missing_response = client.get("/api/public/_test/definitely-missing")
    server_response = client.get("/api/public/_test/returned-503")

    client_events = [
        record for record in _client_errors(log_records)
        if record["extra"].get("request_id") == missing_response.headers["X-Request-ID"]
    ]
    server_events = [
        record for record in _server_errors(log_records)
        if record["extra"].get("request_id") == server_response.headers["X-Request-ID"]
    ]
    assert missing_response.status_code == 404
    assert server_response.status_code == 503
    assert len(client_events) == 1
    assert len(server_events) == 1
    assert client_events[0]["extra"]["route"] == "<unresolved>"
    assert server_events[0]["extra"]["route"] == "/api/public/_test/returned-503"


def _traceback_test_app():
    app = FastAPI()

    @app.get("/boom")
    async def boom():
        raise RuntimeError("PRIVATE_DEV_TRACE_MESSAGE")

    app.add_middleware(UnhandledExceptionMiddleware)
    app.add_middleware(ErrorTrackingMiddleware)
    app.add_middleware(RequestIDMiddleware, generator=lambda: "RID_TRACE")
    return app


def test_dev_console_prints_full_traceback_to_stderr_only(
    log_records, capsys, monkeypatch,
):
    monkeypatch.setattr(settings, "ENVIRONMENT", "DEV")

    response = TestClient(_traceback_test_app()).get("/boom")

    captured = capsys.readouterr()
    assert response.status_code == 500
    # 개발 콘솔(stderr)에는 호출 체인 전체와 예외 메시지 원문이 보인다.
    assert "Traceback (most recent call last)" in captured.err
    assert "PRIVATE_DEV_TRACE_MESSAGE" in captured.err
    assert "boom" in captured.err
    # loguru 경로(파일/Alloy/Loki)로는 여전히 bounded metadata 만 흐른다.
    assert "PRIVATE_DEV_TRACE_MESSAGE" not in repr(log_records)
    server_errors = _server_errors(log_records)
    assert len(server_errors) == 1
    assert server_errors[0]["extra"]["error_type"] == "RuntimeError"


def test_production_never_prints_traceback_to_stderr(
    log_records, capsys, monkeypatch,
):
    monkeypatch.setattr(settings, "ENVIRONMENT", "PROD")

    response = TestClient(_traceback_test_app()).get("/boom")

    captured = capsys.readouterr()
    assert response.status_code == 500
    assert "Traceback" not in captured.err
    assert "PRIVATE_DEV_TRACE_MESSAGE" not in captured.err
    assert len(_server_errors(log_records)) == 1


def test_validation_422_logs_bounded_reason_without_user_input(log_records):
    app = FastAPI()

    class RegisterBody(BaseModel):
        age: int

    @app.post("/register")
    async def register(body: RegisterBody):
        return {"ok": True}

    app.add_exception_handler(RequestValidationError, handle_validation_error)
    app.add_middleware(ErrorTrackingMiddleware)
    app.add_middleware(RequestIDMiddleware, generator=lambda: "RID_422")

    response = TestClient(app).post("/register", json={"age": "PRIVATE_안녕_INPUT"})

    client_errors = _client_errors(log_records)
    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] == "PRIVATE_안녕_INPUT"
    assert len(client_errors) == 1
    assert "PRIVATE_안녕_INPUT" not in repr(client_errors)
    _assert_client_error(client_errors[0], {
        "request_id": "RID_422",
        "method": "POST",
        "path": "/register",
        "route": "/register",
        "status_code": 422,
        "user_id": None,
        "validation_errors": "body.age: int_parsing",
    })


def test_validation_summary_masks_client_supplied_loc_parts():
    # extra_forbidden 의 필드명과 dict body 의 키는 클라이언트 원문 — 마스킹돼야 한다.
    exc = SimpleNamespace(errors=lambda: [
        {"loc": ("body", "kim.secret@example.com"), "type": "extra_forbidden"},
        {"loc": ("body", "counts", "주민번호-950101-1234567"), "type": "int_parsing"},
        {"loc": ("body", "items", 0, "age"), "type": "int_parsing"},
    ])

    summary = _validation_error_summary(exc)

    assert summary == (
        "body.<extra>: extra_forbidden; "
        "body.counts.<key>: int_parsing; "
        "body.items.0.age: int_parsing"
    )
    assert "kim.secret" not in summary
    assert "주민번호" not in summary


def test_validation_summary_masks_identifier_like_extra_field():
    # 식별자 형태여도 extra_forbidden 필드명은 정의상 클라이언트가 보낸 값이다.
    exc = SimpleNamespace(errors=lambda: [
        {"loc": ("body", "password123"), "type": "extra_forbidden"},
    ])

    assert _validation_error_summary(exc) == "body.<extra>: extra_forbidden"


def test_resolve_route_caches_by_route_identity(log_records):
    middleware = ErrorTrackingMiddleware(_unused_app)
    route = SimpleNamespace(path="/api/items/{item_id}")
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/items/1",
        "query_string": b"",
        "headers": [],
        "client": None,
        "scheme": "http",
        "server": ("testserver", 80),
        "state": {},
        "route": route,
    })

    first = middleware._resolve_route(request, ())
    # 캐시 적중을 강제 확인 — 두 번째 호출은 라우트 테이블을 다시 걷지 않는다.
    middleware._route_templates[id(route)] = "/cached/marker"
    second = middleware._resolve_route(request, ())

    assert first == "/api/items/{item_id}"
    assert second == "/cached/marker"


def test_probe_routes_single_source_matches_health_router():
    from app.api.v1.health import router as health_router
    from app.core.probe import PROBE_ROUTES

    assert {route.path for route in health_router.routes} == set(PROBE_ROUTES)


async def test_deep_health_failure_logs_bounded_store_status(monkeypatch, tmp_path):
    secret = "PRIVATE_STORE_CONNECTION_DETAIL_7X9"
    log_path = tmp_path / "deep-health.jsonl"

    async def failed_pings(_request):
        return {
            "postgres": TimeoutError(secret),
            "mongodb": object(),
            "redis_hot": ConnectionError(secret),
            "redis_dedupe": object(),
        }

    monkeypatch.setattr(health, "_run_deep_pings", failed_pings)

    sink_id = logger.add(log_path, serialize=True)
    try:
        response = await health.deep_health(Request({"type": "http"}))
    finally:
        logger.remove(sink_id)

    raw_log = log_path.read_text(encoding="utf-8")
    records = [
        json.loads(line)["record"] for line in raw_log.splitlines()
    ]
    records = [
        record for record in records
        if record["extra"].get("logger_name") == "health"
        and record["message"] == "health/deep 실패"
    ]
    assert response.status_code == 503
    assert len(records) == 1
    assert records[0]["extra"] == {
        "logger_name": "health",
        "failed_store_count": 2,
        "store_status": {
            "postgres": "TimeoutError",
            "mongodb": "ok",
            "redis_hot": "ConnectionError",
            "redis_dedupe": "ok",
        },
    }
    assert secret not in raw_log


def test_validation_error_summary_is_bounded():
    exc = SimpleNamespace(errors=lambda: [
        {"loc": ("body", f"field_{i}"), "type": "missing"} for i in range(8)
    ])

    summary = _validation_error_summary(exc)

    assert summary == (
        "body.field_0: missing; body.field_1: missing; body.field_2: missing; "
        "body.field_3: missing; body.field_4: missing; +3 more"
    )


def test_production_app_registers_validation_context_handler(log_records):
    response = TestClient(create_app()).get("/api/auth/login/app/callback")

    client_errors = _client_errors(log_records)
    assert response.status_code == 422
    assert len(client_errors) == 1
    assert client_errors[0]["extra"]["validation_errors"] == (
        "query.code: missing; query.state: missing"
    )


def test_logs_success_info_once_with_full_request_context(log_records):
    app = FastAPI()

    @app.get("/items/{item_id}")
    async def get_item(item_id: str):
        return {"item_id": item_id}

    app.add_middleware(ErrorTrackingMiddleware)
    app.add_middleware(RequestIDMiddleware, generator=lambda: "RID_SUCCESS")

    response = TestClient(app).get("/items/PRIVATE_ITEM")

    success_events = _success_events(log_records)
    assert response.status_code == 200
    assert len(success_events) == 1
    assert "PRIVATE_ITEM" not in repr(success_events)
    record = success_events[0]
    assert record["level"].name == "INFO"
    assert record["message"] == "HTTP request completed"
    process_time = record["extra"]["process_time"]
    assert isinstance(process_time, float)
    assert record["extra"] == {
        "logger_name": "middleware.error_tracking",
        "event": "http_success",
        "request_id": "RID_SUCCESS",
        "method": "GET",
        "path": "/items/{item_id}",
        "route": "/items/{item_id}",
        "status_code": 200,
        "user_id": None,
        "process_time": process_time,
    }


@pytest.mark.parametrize("probe_route", ["/health", "/health/deep", "/ready"])
async def test_health_probe_success_is_not_info_logged(probe_route, log_records):
    request = Request({
        "type": "http",
        "method": "GET",
        "path": probe_route,
        "query_string": b"",
        "headers": [],
        "client": None,
        "scheme": "http",
        "server": ("testserver", 80),
        "state": {"request_id": "RID_PROBE"},
        "route": SimpleNamespace(path=probe_route),
    })
    middleware = ErrorTrackingMiddleware(_unused_app)

    response = await middleware.dispatch(request, _respond(200, {"status": "ok"}))

    assert response.status_code == 200
    assert _success_events(log_records) == []


async def test_health_probe_failure_is_still_error_logged(log_records):
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/health/deep",
        "query_string": b"",
        "headers": [],
        "client": None,
        "scheme": "http",
        "server": ("testserver", 80),
        "state": {"request_id": "RID_PROBE_FAIL"},
        "route": SimpleNamespace(path="/health/deep"),
    })
    middleware = ErrorTrackingMiddleware(_unused_app)

    response = await middleware.dispatch(request, _respond(503, {"status": "fail"}))

    assert response.status_code == 503
    assert len(_server_errors(log_records)) == 1
    assert _success_events(log_records) == []


async def test_unresolved_route_success_is_not_info_logged(log_records):
    # CORS preflight 는 라우터 도달 전에 2xx 로 끝나 route 가 없다 — API 호출로 세지 않는다.
    request = Request({
        "type": "http",
        "method": "OPTIONS",
        "path": "/api/items",
        "query_string": b"",
        "headers": [],
        "client": None,
        "scheme": "http",
        "server": ("testserver", 80),
        "state": {"request_id": "RID_PREFLIGHT"},
    })
    middleware = ErrorTrackingMiddleware(_unused_app)

    response = await middleware.dispatch(request, _respond(200, {}))

    assert response.status_code == 200
    assert _success_events(log_records) == []


@pytest.mark.parametrize("status_code", [404, 500])
async def test_error_responses_are_not_info_logged_as_success(status_code, log_records):
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/api/items/ITEM_1",
        "query_string": b"",
        "headers": [],
        "client": None,
        "scheme": "http",
        "server": ("testserver", 80),
        "state": {"request_id": "RID_ERR"},
        "route": SimpleNamespace(path="/api/items/{item_id}"),
    })
    middleware = ErrorTrackingMiddleware(_unused_app)

    await middleware.dispatch(request, _respond(status_code, {}))

    assert _success_events(log_records) == []


@pytest.mark.parametrize("status_code", [200, 399, 500])
async def test_does_not_classify_non_4xx_responses_as_client_errors(status_code, log_records):
    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/health",
        "query_string": b"",
        "headers": [],
        "client": None,
        "scheme": "http",
        "server": ("testserver", 80),
        "state": {"request_id": "RID_2"},
    })
    middleware = ErrorTrackingMiddleware(_unused_app)

    await middleware.dispatch(
        request,
        _respond(status_code, {}),
    )

    assert not any(
        record["extra"].get("event") == "http_client_error"
        for record in log_records
    )


def test_logs_validation_response_from_fastapi_exception_handler(log_records):
    app = FastAPI()

    @app.get("/items/{item_id}")
    async def get_item(item_id: str, limit: int = Query(...)):
        return {"item_id": item_id, "limit": limit}

    app.add_middleware(ErrorTrackingMiddleware)
    app.add_middleware(RequestIDMiddleware, generator=lambda: "RID_VALIDATION")

    response = TestClient(app).get("/items/ITEM_1", params={"limit": "invalid"})

    client_errors = _client_errors(log_records)
    assert response.status_code == 422
    assert len(client_errors) == 1
    _assert_client_error(client_errors[0], {
        "request_id": "RID_VALIDATION",
        "method": "GET",
        "path": "/items/{item_id}",
        "route": "/items/{item_id}",
        "status_code": 422,
        "user_id": None,
    })


def test_logs_http_exception_with_consistent_request_context(log_records):
    app = FastAPI()

    @app.get("/teapot")
    async def teapot():
        raise HTTPException(status_code=418, detail="short and stout")

    app.add_middleware(ErrorTrackingMiddleware)
    app.add_middleware(RequestIDMiddleware, generator=lambda: "RID_HTTP_EXCEPTION")

    response = TestClient(app).get("/teapot")

    client_errors = _client_errors(log_records)
    assert response.status_code == 418
    assert len(client_errors) == 1
    _assert_client_error(client_errors[0], {
        "request_id": "RID_HTTP_EXCEPTION",
        "method": "GET",
        "path": "/teapot",
        "route": "/teapot",
        "status_code": 418,
        "user_id": None,
    })


def test_logs_auth_middleware_short_circuit_once(log_records):
    app = FastAPI()
    app.add_middleware(BearerTokenMiddleware)
    app.add_middleware(ErrorTrackingMiddleware)
    app.add_middleware(RequestIDMiddleware, generator=lambda: "RID_AUTH")

    response = TestClient(app).get("/protected/SECRET_PATH_VALUE")

    client_errors = _client_errors(log_records)
    middleware_records = [
        record for record in log_records
        if record["extra"].get("logger_name", "").startswith("middleware.")
    ]
    assert response.status_code == 401
    assert len(client_errors) == 1
    assert "SECRET_PATH_VALUE" not in repr(middleware_records)
    _assert_client_error(client_errors[0], {
        "request_id": "RID_AUTH",
        "method": "GET",
        "path": "<unresolved>",
        "route": "<unresolved>",
        "status_code": 401,
        "user_id": None,
    })


def test_security_headers_wrap_auth_short_circuit():
    response = TestClient(create_app()).get("/api/tripmate/posts/SECRET_PATH_VALUE")

    assert response.status_code == 401
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_logs_cors_rejection_in_application_stack(log_records):
    app = create_app()

    response = TestClient(app).options(
        "/api/tripmate/posts",
        headers={
            "Origin": "https://untrusted.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    client_errors = _client_errors(log_records)
    assert response.status_code == 400
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert len(client_errors) == 1
    _assert_client_error(client_errors[0], {
        "request_id": response.headers["X-Request-ID"],
        "method": "OPTIONS",
        "path": "<unresolved>",
        "route": "<unresolved>",
        "status_code": 400,
        "user_id": None,
    })


def test_tracking_logs_never_contain_secret_path_parameter(log_records):
    share_token = "SECRET_SHARE_TOKEN_NOT_JWT"

    response = TestClient(create_app()).get(f"/api/public/share/plan/{share_token}")

    tracking_records = [
        record for record in log_records
        if record["extra"].get("logger_name", "").startswith("middleware.")
    ]
    client_errors = _client_errors(tracking_records)
    assert response.status_code == 400
    assert len(client_errors) == 1
    assert share_token not in repr(tracking_records)
    assert client_errors[0]["extra"]["route"] == (
        "/api/public/share/plan/{share_token}"
    )


@pytest.mark.parametrize(
    ("mount_path", "route_path", "request_path", "expected_route"),
    [
        (
            "/share/{share_token}",
            "/items/{item_id}",
            "/share/MOUNT_SECRET/items/ITEM_SECRET",
            "/share/{share_token}/items/{item_id}",
        ),
        (
            "/prefix/files/foo",
            "/files/{file_path:path}",
            "/prefix/files/foo/files/a/b",
            "/prefix/files/foo/files/{file_path:path}",
        ),
    ],
)
def test_logs_full_safe_route_template_across_mounts(
    mount_path, route_path, request_path, expected_route, log_records,
):
    child = FastAPI()

    @child.get(route_path)
    async def reject():
        raise HTTPException(status_code=400)

    app = FastAPI()
    app.mount(mount_path, child)
    app.add_middleware(ErrorTrackingMiddleware)
    app.add_middleware(RequestIDMiddleware, generator=lambda: "RID_MOUNT")

    response = TestClient(app).get(request_path)

    client_errors = _client_errors(log_records)
    assert response.status_code == 400
    assert len(client_errors) == 1
    assert client_errors[0]["extra"]["path"] == expected_route
    assert client_errors[0]["extra"]["route"] == expected_route
    assert "MOUNT_SECRET" not in repr(client_errors)


async def test_client_error_log_includes_stamped_error_detail(log_records):
    """handle_http_exception/handle_domain_error 가 심은 detail 이 4xx 로그 필드로 노출된다."""
    from app.middleware.tracking import handle_http_exception

    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/api/auth/register",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "scheme": "http",
        "server": ("testserver", 80),
        "state": {"request_id": "RID_1", "user_id": "USER_1"},
        "route": SimpleNamespace(path="/api/auth/register"),
    })
    exc = HTTPException(status_code=409, detail="이미 2차 회원가입이 완료된 유저입니다.")
    await handle_http_exception(request, exc)

    middleware = ErrorTrackingMiddleware(_unused_app)
    response = await middleware.dispatch(
        request,
        _respond(409, {"detail": "이미 2차 회원가입이 완료된 유저입니다."}),
    )

    client_errors = _client_errors(log_records)
    assert response.status_code == 409
    assert len(client_errors) == 1
    assert client_errors[0]["extra"]["error_detail"] == (
        "이미 2차 회원가입이 완료된 유저입니다."
    )


async def test_stamped_error_detail_is_truncated(log_records):
    from app.middleware.tracking import _ERROR_DETAIL_MAX_LEN, _stamp_error_detail

    request = Request({
        "type": "http",
        "method": "GET",
        "path": "/x",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 1234),
        "scheme": "http",
        "server": ("testserver", 80),
        "state": {},
    })
    _stamp_error_detail(request, "가" * 500)

    assert len(request.state.error_detail) == _ERROR_DETAIL_MAX_LEN
