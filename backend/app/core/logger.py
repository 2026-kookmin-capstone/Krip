"""로깅 설정 (loguru)

환경변수:
  LOG_LEVEL       최소 출력 레벨 (TRACE<DEBUG<INFO<SUCCESS<WARNING<ERROR<CRITICAL)
  LOG_FORMAT      "json"(수집/분석용) | "console"(로컬 디버깅용). PROD 는 항상 json 강제.
  LOG_FILE_PATH   None 이면 콘솔만, 경로 지정 시 파일에도 기록
  LOG_ROTATION    "100 MB" 등 용량/시간 기준으로 롤테이션 (loguru 규칙)
  LOG_RETENTION   "14 days" 등 경과 후 자동 삭제
  LOG_COMPRESSION "gz" 등 롤테이션 파일 압축

사용:
  logger = get_logger("service_name")
  logger.bind(user_id=123).info("서비스 완료")

포맷팅: f-string 대신 loguru {} 포맷을 써 레벨 비활성 시 문자열 조합을 생략한다.
  logger.info("유저: {}", user_id)      # (O)
  logger.info(f"유저: {user_id}")       # (X) 항상 평가됨
"""
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from loguru import logger as _logger
from loguru._file_sink import FileSink

from app.config.setting import settings
from app.core.context import request_id_var


def exception_context(error: BaseException) -> dict[str, str | int | None]:
    traceback = error.__traceback__
    if traceback is None:
        location = None
        line = None
    else:
        while traceback.tb_next is not None:
            traceback = traceback.tb_next
        module = traceback.tb_frame.f_globals.get("__name__", "<unknown>")
        location = f"{module}:{traceback.tb_frame.f_code.co_name}"
        line = traceback.tb_lineno
    return {
        "error_type": type(error).__name__,
        "error_location": location,
        "error_line": line,
    }


def _sanitize_log_value(
    value: Any,
    errors: list[BaseException],
    active: set[int] | None = None,
) -> Any:
    if isinstance(value, BaseException):
        errors.append(value)
        return type(value).__name__
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if not isinstance(value, (dict, list, tuple, set, frozenset)):
        return type(value).__name__

    active = active or set()
    identity = id(value)
    if identity in active:
        return "<recursive>"
    active.add(identity)
    try:
        if isinstance(value, dict):
            sanitized = {}
            for key, item in value.items():
                safe_key = _sanitize_log_value(key, errors, active)
                try:
                    hash(safe_key)
                except TypeError:
                    safe_key = f"<{type(key).__name__}>"
                sanitized[safe_key] = _sanitize_log_value(item, errors, active)
            return sanitized
        items = [_sanitize_log_value(item, errors, active) for item in value]
        if isinstance(value, list):
            return items
        if isinstance(value, tuple):
            return tuple(items)
        return items
    finally:
        active.remove(identity)


def _bind_request_context(record) -> None:
    """요청 컨텍스트를 주입하고 예외 payload/traceback을 안전한 메타데이터로 축약."""
    request_id = request_id_var.get()
    if request_id:
        record["extra"].setdefault("request_id", request_id)
    errors = []
    record["extra"] = {
        key: _sanitize_log_value(value, errors)
        for key, value in record["extra"].items()
    }
    exception = record.get("exception")
    if exception is not None:
        if isinstance(exception.value, BaseException):
            errors.insert(0, exception.value)
        record["exception"] = None
    if errors:
        record["extra"].update(exception_context(errors[0]))


class SafeLogger:
    """예외 객체가 format argument를 통해 원문으로 직렬화되지 않게 하는 Loguru adapter."""

    _LEVEL_METHODS = {
        "trace", "debug", "info", "success", "warning", "error", "critical", "exception",
    }

    def __init__(self, wrapped: Any, depth: int = 0) -> None:
        self._wrapped = wrapped
        self._depth = depth

    @staticmethod
    def _safe_values(values):
        errors = []
        sanitized = tuple(_sanitize_log_value(value, errors) for value in values)
        return sanitized, errors[0] if errors else None

    @staticmethod
    def _safe_message(message: Any) -> tuple[str, BaseException | None]:
        errors = []
        sanitized = _sanitize_log_value(message, errors)
        safe_message = sanitized if isinstance(sanitized, str) else str(sanitized)
        return safe_message, errors[0] if errors else None

    def bind(self, **kwargs) -> "SafeLogger":
        errors = []
        sanitized = {
            key: _sanitize_log_value(value, errors)
            for key, value in kwargs.items()
        }
        if errors:
            sanitized.update(exception_context(errors[0]))
        return SafeLogger(self._wrapped.bind(**sanitized), self._depth)

    def opt(self, *args, **kwargs) -> "SafeLogger":
        unsupported = set(kwargs) - {"depth", "exception"}
        if args or unsupported:
            names = sorted(unsupported) if unsupported else ["positional arguments"]
            raise ValueError(f"unsupported SafeLogger.opt options: {', '.join(names)}")

        depth = kwargs.get("depth", 0)
        if type(depth) is not int or depth < 0:
            raise ValueError("SafeLogger.opt depth must be a non-negative integer")
        exception = kwargs.get("exception")
        error = None
        if isinstance(exception, BaseException):
            error = exception
        elif (
            isinstance(exception, tuple)
            and len(exception) > 1
            and isinstance(exception[1], BaseException)
        ):
            error = exception[1]
        elif exception is True:
            error = sys.exception()

        wrapped = self._wrapped.bind(**exception_context(error)) if error else self._wrapped
        return SafeLogger(wrapped, self._depth + depth)

    def _emit(self, method: str, message: Any, *args, **kwargs) -> Any:
        safe_message, message_error = self._safe_message(message)
        safe_args, positional_error = self._safe_values(args)
        keyword_errors = []
        safe_kwargs = {
            key: _sanitize_log_value(value, keyword_errors)
            for key, value in kwargs.items()
        }
        error = message_error or positional_error or (
            keyword_errors[0] if keyword_errors else None
        )
        wrapped = self._wrapped.bind(**exception_context(error)) if error else self._wrapped
        wrapped = wrapped.opt(depth=2 + self._depth)
        return getattr(wrapped, method)(safe_message, *safe_args, **safe_kwargs)

    def log(self, level: str | int, message: Any, *args, **kwargs) -> Any:
        safe_message, message_error = self._safe_message(message)
        safe_args, positional_error = self._safe_values(args)
        keyword_errors = []
        safe_kwargs = {
            key: _sanitize_log_value(value, keyword_errors)
            for key, value in kwargs.items()
        }
        error = message_error or positional_error or (
            keyword_errors[0] if keyword_errors else None
        )
        wrapped = self._wrapped.bind(**exception_context(error)) if error else self._wrapped
        return wrapped.opt(depth=1 + self._depth).log(
            level, safe_message, *safe_args, **safe_kwargs
        )

    def __getattr__(self, name: str):
        if name in self._LEVEL_METHODS:
            return lambda message, *args, **kwargs: self._emit(
                name, message, *args, **kwargs
            )
        raise AttributeError(f"SafeLogger does not expose Loguru.{name}()")


def _private_file_opener(path: str, flags: int) -> int:
    return os.open(path, flags, 0o600)


def _private_compression(compression: str) -> Callable[[str], None]:
    compress = FileSink._make_compression_function(compression)
    if compress is None:
        raise ValueError("LOG_COMPRESSION must not be empty")
    suffix = f".{compression.strip().lstrip('.')}"

    def compress_private(path: str) -> None:
        compress(path)
        Path(f"{path}{suffix}").chmod(0o600)

    return compress_private


def setup_logging() -> None:
    """로깅 시스템 설정"""

    # PROD + console 포맷은 Alloy JSON parser를 깨뜨리므로 json으로 강제한다.
    # 발화 알림은 sink 가 준비된 함수 끝에서 emit (remove~add 사이엔 sink 부재).
    requested_format = settings.LOG_FORMAT
    forced_json = settings.is_production and requested_format != "json"
    log_format = "json" if forced_json else requested_format

    _logger.remove()
    _logger.configure(patcher=_bind_request_context)

    # 콘솔 출력
    if log_format == "json":
        _logger.add(
            sys.stdout,
            format="{message}",
            serialize=True,
            level=settings.LOG_LEVEL,
            diagnose=False,
            backtrace=False,
            enqueue=True
        )
    else:
        _logger.add(
            sys.stdout,
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level> | {extra}",
            level=settings.LOG_LEVEL,
            colorize=True,
            diagnose=False,
            backtrace=False,
            enqueue=True
        )

    # 파일 출력
    # LOG_FILE_PATH 기본값이 컨테이너 절대경로라 로컬/CI 에서 mkdir 이 OSError 로 부팅을 막을 수 있음.
    if settings.LOG_FILE_PATH:
        try:
            log_path = Path(settings.LOG_FILE_PATH)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.touch(mode=0o600, exist_ok=True)
            log_path.chmod(0o600)
            archive_pattern = f"{log_path.stem}.*{log_path.suffix}*"
            for archived_path in log_path.parent.glob(archive_pattern):
                if archived_path.is_file():
                    archived_path.chmod(0o600)

            _logger.add(
                settings.LOG_FILE_PATH,
                rotation=settings.LOG_ROTATION,
                retention=settings.LOG_RETENTION,
                compression=_private_compression(settings.LOG_COMPRESSION),
                format="{message}",
                serialize=True,
                level=settings.LOG_LEVEL,
                diagnose=False,
                backtrace=False,
                encoding="utf-8",
                opener=_private_file_opener,
                enqueue=True
            )
        except OSError as e:
            # 이미 등록된 콘솔 sink 로 경고만 남기고 파일 sink 없이 진행 (부팅 차단 방지).
            _logger.warning(
                "파일 sink 초기화 실패({}) — 콘솔 출력만으로 계속합니다.",
                type(e).__name__,
            )
    
    # 표준 logging 을 loguru 로 흘려보내는 핸들러
    class InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                level = _logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            # logging 내부 프레임을 건너뛰어 실제 호출 지점의 depth 를 찾는다.
            frame, depth = logging.currentframe(), 0
            while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
                frame = frame.f_back
                depth += 1

            error = None
            if isinstance(record.args, tuple):
                error = next(
                    (value for value in record.args if isinstance(value, BaseException)),
                    None,
                )
            elif isinstance(record.args, dict):
                error = next(
                    (value for value in record.args.values() if isinstance(value, BaseException)),
                    None,
                )

            if record.exc_info and record.exc_info[1] is not None:
                error = record.exc_info[1]
            target = _logger.bind(
                event="stdlib_log",
                source_logger=record.name,
                source_level=record.levelname,
                **(exception_context(error) if error else {}),
            )
            target.opt(depth=depth, exception=record.exc_info).log(
                level, "Standard library log event"
            )

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # uvicorn CLI 는 자기 로거에 plain-text 핸들러를 propagate=False 로 심는다.
    # basicConfig(force=True) 는 root 만 건드리므로 그대로 두면 JSON stdout 에
    # plain-text가 섞여 Alloy parsing이 깨진다. 핸들러를 비우고 propagate를 살려
    # loguru 단일 경로로 통합한다.
    for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        _uvicorn_logger = logging.getLogger(_name)
        _uvicorn_logger.handlers.clear()
        _uvicorn_logger.propagate = True

    logging.getLogger("uvicorn").setLevel(logging.INFO)
    access_logger = logging.getLogger("uvicorn.access")
    access_logger.propagate = False
    access_logger.disabled = True
    for logger_name in ("httpx", "httpcore"):
        client_logger = logging.getLogger(logger_name)
        client_logger.setLevel(logging.WARNING)
        client_logger.disabled = True
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # json 강제 알림 — 운영자가 .env 에 박은 원래 값(requested_format)을 보여준다.
    if forced_json:
        _logger.warning(
            "PROD 환경에서 LOG_FORMAT={} 가 지정되어 있어 json 으로 강제 변환했습니다. "
            "Alloy JSON parser 호환 보호.",
            requested_format,
        )

    _logger.info("Logging system initialized with level: {}", settings.LOG_LEVEL)


def get_logger(name: str) -> SafeLogger:
    """이름이 지정된 로거 가져오기"""
    return SafeLogger(_logger.bind(logger_name=name))


# 전역 로거 인스턴스
app_logger = get_logger("app")