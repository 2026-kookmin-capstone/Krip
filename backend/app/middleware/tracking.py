import time
import traceback
import uuid
from typing import Callable, Optional

from fastapi import Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from app.config.setting import settings
from app.core.context import db_route_var, request_id_var
from app.core.instrumentation import db_route_for_path
from app.core.logger import exception_context, get_logger
from app.core.probe import PROBE_ROUTES


_UNRESOLVED_ROUTE = "<unresolved>"


def _find_route_template(routes, selected_route, prefix: str = "") -> str | None:
    for route in routes:
        contexts = getattr(route, "effective_route_contexts", None)
        if contexts is not None:
            for context in contexts():
                if context.original_route is selected_route:
                    return f"{prefix}{context.path}"

        path = getattr(route, "path", "") or ""
        template = f"{prefix}{path}"
        if route is selected_route:
            return template

        nested_routes = getattr(route, "routes", None)
        if nested_routes:
            nested = _find_route_template(nested_routes, selected_route, template)
            if nested is not None:
                return nested
    return None


def _route_template(request: Request, routes=()) -> str:
    selected_route = request.scope.get("route")
    if selected_route is None:
        return _UNRESOLVED_ROUTE

    template = _find_route_template(routes, selected_route)
    if template is not None:
        return template
    return getattr(selected_route, "path", _UNRESOLVED_ROUTE)


def _trusted_request_id(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        canonical = str(uuid.UUID(value))
    except (ValueError, AttributeError):
        return None
    return canonical if value.lower() == canonical else None


_MAX_VALIDATION_ERRORS = 5


def _safe_loc_part(part: object) -> str:
    if isinstance(part, int):
        return str(part)
    text = str(part)
    if text.isidentifier() and len(text) <= 64:
        return text
    return "<key>"


def _validation_error_summary(exc: RequestValidationError) -> str:
    errors = exc.errors()
    parts = []
    for error in errors[:_MAX_VALIDATION_ERRORS]:
        loc = [_safe_loc_part(part) for part in error.get("loc", ())]
        if error.get("type") == "extra_forbidden" and loc:
            loc[-1] = "<extra>"  # 마지막 파트는 정의상 클라이언트가 보낸 필드명
        parts.append(
            "{}: {}".format(".".join(loc) or "<unknown>", error.get("type", "<unknown>"))
        )
    overflow = len(errors) - _MAX_VALIDATION_ERRORS
    if overflow > 0:
        parts.append(f"+{overflow} more")
    return "; ".join(parts)


async def handle_domain_error(request: Request, exc: Exception) -> Response:
    """except 를 등록하지 않은 엔드포인트의 도메인 예외를 500 대신 선언된 status 로 응답."""
    return JSONResponse(
        status_code=getattr(exc, "status_code", 400),
        content={"detail": str(exc)},
    )


async def handle_validation_error(
    request: Request, exc: RequestValidationError,
) -> Response:
    """422 사유를 스키마 위치(loc)·오류 종류(type)로만 로그 컨텍스트에 남긴다.

    msg 는 커스텀 validator 가 입력값을 문장에 섞을 수 있고 input 은 사용자
    원문 그 자체라 금지 — 둘 다 응답 body 로만 내려간다.
    """
    request.state.validation_errors = _validation_error_summary(exc)
    return await request_validation_exception_handler(request, exc)


class RequestIDMiddleware(BaseHTTPMiddleware):
    """요청 ID를 생성하고 추적하는 미들웨어"""
    
    def __init__(
        self,
        app: ASGIApp,
        header_name: str = "X-Request-ID",
        generator: Optional[Callable[[], str]] = None,
    ) -> None:
        super().__init__(app)
        self.header_name = header_name
        self.generator = generator or self._default_generator
        self.logger = get_logger("middleware.request_tracking")

    @staticmethod
    def _default_generator() -> str:
        """기본 요청 ID 생성기"""
        return str(uuid.uuid4())

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = _trusted_request_id(request.headers.get(self.header_name)) or self.generator()

        request.state.request_id = request_id

        # contextvar 에 set — FanoutService 등 깊은 호출 스택에서 envelope 에 박을 때 사용.
        rid_token = request_id_var.set(request_id)
        # DB query / transaction 메트릭의 route 라벨 — 도메인 단위 매핑.
        route_token = db_route_var.set(db_route_for_path(request.url.path))

        self.logger.bind(
            request_id=request_id,
            method=request.method,
        ).debug("요청 ID 할당됨")

        try:
            response = await call_next(request)
        finally:
            db_route_var.reset(route_token)
            request_id_var.reset(rid_token)

        response.headers[self.header_name] = request_id

        return response


def _emit_dev_traceback(error: BaseException) -> None:
    """DEV 콘솔 전용 전체 traceback.

    stderr 는 loguru sink 를 거치지 않으므로 파일 sink → Alloy → Loki 경로에
    진입할 수 없다. PROD 는 bounded metadata(error_type/location/line)만 남긴다.
    """
    if settings.is_production:
        return
    traceback.print_exception(error)


class UnhandledExceptionMiddleware(BaseHTTPMiddleware):
    """라우터 예외를 CORS 내부에서 안전한 500 응답과 bounded metadata로 변환한다."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            return await call_next(request)
        except Exception as error:
            _emit_dev_traceback(error)
            request.state.http_error_context = exception_context(error)
            return JSONResponse(
                status_code=500,
                content={"detail": "Internal Server Error"},
            )


class ErrorTrackingMiddleware(BaseHTTPMiddleware):
    """에러 추적 및 모니터링 미들웨어."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self.logger = get_logger("middleware.error_tracking")
        # route 객체는 앱 수명 동안 불변 — 요청마다 전체 라우트 테이블을 순회하지 않는다.
        self._route_templates: dict[int, str] = {}

    def _resolve_route(self, request: Request, routes) -> str:
        selected_route = request.scope.get("route")
        if selected_route is None:
            return _UNRESOLVED_ROUTE
        key = id(selected_route)
        template = self._route_templates.get(key)
        if template is None:
            template = _route_template(request, routes)
            self._route_templates[key] = template
        return template

    @staticmethod
    def _request_context(
        request: Request, *, request_id: str, route: str, status_code: int,
    ) -> dict[str, str | int | None]:
        return {
            "request_id": request_id,
            "method": request.method,
            "path": route,
            "route": route,
            "status_code": status_code,
            "user_id": getattr(request.state, "user_id", None),
        }

    def _log_http_success(
        self,
        request: Request,
        *,
        request_id: str,
        route: str,
        status_code: int,
        process_time: float,
    ) -> None:
        context = self._request_context(
            request, request_id=request_id, route=route, status_code=status_code,
        )
        self.logger.bind(
            event="http_success",
            **context,
            process_time=process_time,
        ).info("HTTP request completed")

    def _log_http_error(
        self,
        request: Request,
        *,
        request_id: str,
        route: str,
        status_code: int,
        error_fields: dict[str, str | int | None] | None = None,
    ) -> None:
        context = self._request_context(
            request, request_id=request_id, route=route, status_code=status_code,
        )
        if status_code < 500:
            validation_errors = getattr(request.state, "validation_errors", None)
            if validation_errors:
                context["validation_errors"] = validation_errors
            self.logger.bind(event="http_client_error", **context).warning(
                "HTTP client error response"
            )
            return

        error_fields = error_fields or dict.fromkeys((
            "error_type", "error_location", "error_line",
            "error_app_location", "error_app_line", "error_cause",
        ))
        self.logger.bind(
            event="http_server_error",
            **context,
            **error_fields,
        ).error("HTTP server error response")

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.perf_counter()
        request_id = getattr(request.state, "request_id", "unknown")
        routes = getattr(request.scope.get("app"), "routes", ())

        try:
            response = await call_next(request)

            process_time = time.perf_counter() - start_time
            response.headers["X-Process-Time"] = str(process_time)
            route = self._resolve_route(request, routes)

            if 400 <= response.status_code < 600:
                self._log_http_error(
                    request,
                    request_id=request_id,
                    route=route,
                    status_code=response.status_code,
                    error_fields=getattr(request.state, "http_error_context", None),
                )
            elif (
                response.status_code < 400
                and route != _UNRESOLVED_ROUTE
                and route not in PROBE_ROUTES
            ):
                self._log_http_success(
                    request,
                    request_id=request_id,
                    route=route,
                    status_code=response.status_code,
                    process_time=process_time,
                )

            self.logger.bind(
                request_id=request_id,
                method=request.method,
                route=route,
                status_code=response.status_code,
                process_time=process_time,
            ).debug("요청 처리 완료")

            return response

        except Exception as error:
            _emit_dev_traceback(error)
            process_time = time.perf_counter() - start_time
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal Server Error"},
            )
            response.headers["X-Process-Time"] = str(process_time)
            self._log_http_error(
                request,
                request_id=request_id,
                route=self._resolve_route(request, routes),
                status_code=500,
                error_fields=exception_context(error),
            )
            return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """보안 헤더 추가 미들웨어"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        return response