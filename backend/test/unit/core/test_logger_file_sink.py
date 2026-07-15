"""setup_logging 파일 sink 실패 시 콘솔 전용 폴백 단위 테스트.

핵심 회귀 검증 (LOG_FILE_PATH 기본값이 컨테이너 절대경로라 로컬/CI 에서 mkdir 이
PermissionError/OSError 로 부팅을 막던 문제 수정):
    - 파일 sink 초기화가 실패해도 setup_logging 이 예외 없이 완료
    - 파일은 생성되지 않고 콘솔 sink 만 남음
    - 경로가 쓰기 가능하면(정상 케이스) 파일 sink 가 정상 등록됨
"""
import inspect
import json
import logging
import stat
from collections import defaultdict, namedtuple
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from loguru import logger

from app.config.setting import Settings, settings
from app.core import logger as logger_module
from app.core.context import request_id_var
from app.domain.auth.model.user_detail_inform import Gender
from app.domain.auth.router import register as register_router
from app.domain.auth.schema.register import RegisterRequest
from app.domain.auth.service.register import RegisterService
from app.main import create_app


def _handler_count() -> int:
    return len(logger._core.handlers)


def _raise_private_frame(secret: str) -> None:
    raise RuntimeError("safe exception message")


def _emit_from_known_caller() -> None:
    logger_module.get_logger("caller.test").info("caller probe")


def _emit_via_opt_and_log(secret: str) -> None:
    error = RuntimeError(secret)
    logger_module.get_logger("caller.test").opt(exception=error).log(
        "ERROR", "safe probe: {}", error
    )


def _log_with_extra_depth(safe_logger) -> None:
    safe_logger.opt(depth=1).info("depth probe")


def test_exception_context_preserves_safe_source_line_without_payload():
    with pytest.raises(RuntimeError) as exc_info:
        _raise_private_frame("PRIVATE_LINE_CONTEXT_7X9")

    context = logger_module.exception_context(exc_info.value)

    assert context == {
        "error_type": "RuntimeError",
        "error_location": f"{__name__}:_raise_private_frame",
        "error_line": _raise_private_frame.__code__.co_firstlineno + 1,
        "error_app_location": None,
        "error_app_line": None,
        "error_cause": None,
    }


def test_exception_context_records_deepest_app_frame_and_explicit_cause():
    # app.* 모듈 프레임을 exec 로 합성 — 실제 워커에서 라이브러리 예외가 통과하는 경로 재현.
    app_ns = {"__name__": "app.fake.worker"}
    exec(
        "def call_lib(lib_fn):\n"
        "    lib_fn()\n",
        app_ns,
    )
    lib_ns = {"__name__": "sqlalchemy.fake.engine"}
    exec(
        "def lib_boom():\n"
        "    raise ConnectionError('lib detail')\n",
        lib_ns,
    )

    with pytest.raises(RuntimeError) as exc_info:
        try:
            app_ns["call_lib"](lib_ns["lib_boom"])
        except ConnectionError as error:
            raise RuntimeError("wrapped") from error

    context = logger_module.exception_context(exc_info.value)

    assert context["error_type"] == "RuntimeError"
    assert context["error_cause"] == "ConnectionError"
    # cause 가 아닌 본 예외의 traceback 기준 — 본 예외는 test 모듈에서 raise 됐다.
    assert context["error_app_location"] is None

    inner_context = logger_module.exception_context(exc_info.value.__cause__)
    assert inner_context["error_location"] == "sqlalchemy.fake.engine:lib_boom"
    assert inner_context["error_app_location"] == "app.fake.worker:call_lib"
    assert inner_context["error_app_line"] == 2


def test_exception_context_ignores_exception_group_cause():
    with pytest.raises(RuntimeError) as exc_info:
        try:
            raise ExceptionGroup("plumbing", [ValueError("x")])
        except ExceptionGroup as group:
            raise RuntimeError("wrapped") from group

    assert logger_module.exception_context(exc_info.value)["error_cause"] is None


def test_sanitize_bounds_recursion_depth_instead_of_raising():
    deep = current = []
    for _ in range(2000):
        nested = []
        current.append(nested)
        current = nested

    records = []
    sink_id = logger.add(lambda message: records.append(message.record), level="DEBUG")
    try:
        logger_module.get_logger("depth.test").bind(payload=deep).info("deep payload")
    finally:
        logger.remove(sink_id)

    assert "<max-depth>" in repr(records[-1]["extra"]["payload"])


def test_safe_logger_recursively_sanitizes_nested_exceptions():
    secret = "PRIVATE_NESTED_EXCEPTION_7X9"
    records = []
    sink_id = logger.add(lambda message: records.append(message.record), level="DEBUG")
    try:
        error = RuntimeError(secret)
        logger_module.get_logger("nested.test").bind(
            bundle={"items": [error], error: {"failure": error}}
        ).error("nested failure")
    finally:
        logger.remove(sink_id)

    serialized = json.dumps(records[-1]["extra"], default=str)
    assert secret not in serialized
    assert records[-1]["extra"]["error_type"] == "RuntimeError"


def test_safe_logger_sanitizes_container_subclasses_and_unknown_objects():
    secret = "PRIVATE_SUBCLASS_EXCEPTION_7X9"
    pair_type = namedtuple("ExceptionPair", "value")

    class SecretPayload:
        def __str__(self) -> str:
            return secret

    records = []
    sink_id = logger.add(lambda message: records.append(message.record), level="DEBUG")
    try:
        error = RuntimeError(secret)
        logger_module.get_logger("subclass.test").bind(
            mapping=defaultdict(list, failure=error),
            sequence=pair_type(error),
            unknown=SecretPayload(),
        ).error("subclass failure")
    finally:
        logger.remove(sink_id)

    serialized = json.dumps(records[-1]["extra"], default=str)
    assert secret not in serialized
    assert records[-1]["extra"]["mapping"] == {"failure": "RuntimeError"}
    assert records[-1]["extra"]["sequence"] == ("RuntimeError",)
    assert records[-1]["extra"]["unknown"] == "SecretPayload"


def test_safe_logger_sanitizes_non_string_messages():
    secret = "PRIVATE_MESSAGE_OBJECT_7X9"

    class SecretPayload:
        def __str__(self) -> str:
            return secret

    records = []
    sink_id = logger.add(lambda message: records.append(message.record), level="DEBUG")
    try:
        safe_logger = logger_module.get_logger("message.test")
        safe_logger.error(RuntimeError(secret))
        safe_logger.log("ERROR", SecretPayload())
    finally:
        logger.remove(sink_id)

    assert [record["message"] for record in records[-2:]] == [
        "RuntimeError",
        "SecretPayload",
    ]
    assert records[-2]["extra"]["error_type"] == "RuntimeError"
    assert secret not in repr(records[-2:])


def test_safe_logger_does_not_expose_raw_loguru_patch():
    with pytest.raises(AttributeError):
        logger_module.get_logger("patch.test").patch(
            lambda record: record["extra"].update(
                error=RuntimeError("PRIVATE_PATCH_EXCEPTION_7X9")
            )
        )


def test_gateway_module_does_not_export_raw_loguru_logger():
    assert not hasattr(logger_module, "logger")


def test_safe_logger_opt_exception_true_is_supported_on_python_311():
    records = []
    sink_id = logger.add(lambda message: records.append(message.record), level="DEBUG")
    try:
        try:
            _raise_private_frame("PRIVATE_OPT_TRUE_7X9")
        except RuntimeError:
            logger_module.get_logger("opt.test").opt(exception=True).error(
                "safe opt true"
            )
    finally:
        logger.remove(sink_id)

    assert records[-1]["extra"]["error_type"] == "RuntimeError"
    assert "PRIVATE_OPT_TRUE_7X9" not in repr(records[-1])


def test_safe_logger_opt_supports_only_privacy_safe_options():
    safe_logger = logger_module.get_logger("opt.options.test")
    for option in ("capture", "colors", "lazy", "raw", "record"):
        with pytest.raises(ValueError, match="unsupported SafeLogger.opt options"):
            safe_logger.opt(**{option: True})


def test_safe_logger_opt_preserves_requested_depth():
    records = []
    sink_id = logger.add(lambda message: records.append(message.record), level="DEBUG")
    try:
        frame = inspect.currentframe()
        assert frame is not None
        expected_line = frame.f_lineno + 1
        _log_with_extra_depth(logger_module.get_logger("opt.depth.test"))
    finally:
        logger.remove(sink_id)

    assert records[-1]["line"] == expected_line


def test_default_file_retention_matches_loki_window():
    assert Settings.model_fields["LOG_RETENTION"].default == "14 days"


def test_request_context_patcher_adds_request_id_without_overwriting_explicit_value():
    token = request_id_var.set("RID_CONTEXT")
    nested_error = RuntimeError("PRIVATE_PATCHER_NESTED_7X9")
    try:
        implicit_record = {"extra": {"bundle": [nested_error]}, "exception": None}
        explicit_record = {"extra": {"request_id": "RID_EXPLICIT"}}

        logger_module._bind_request_context(implicit_record)
        logger_module._bind_request_context(explicit_record)
    finally:
        request_id_var.reset(token)

    assert implicit_record["extra"]["request_id"] == "RID_CONTEXT"
    assert implicit_record["extra"]["bundle"] == ["RuntimeError"]
    assert implicit_record["extra"]["error_type"] == "RuntimeError"
    assert explicit_record["extra"]["request_id"] == "RID_EXPLICIT"


def _stdlib_logger_state(target):
    return (list(target.handlers), target.level, target.disabled, target.propagate)


def _restore_stdlib_logger(target, state):
    handlers, level, disabled, propagate = state
    target.handlers[:] = handlers
    target.setLevel(level)
    target.disabled = disabled
    target.propagate = propagate


@contextmanager
def _preserve_stdlib_logging():
    root = logging.getLogger()
    root_state = _stdlib_logger_state(root)
    logger_states = {
        name: _stdlib_logger_state(candidate)
        for name, candidate in logging.Logger.manager.loggerDict.items()
        if isinstance(candidate, logging.Logger)
    }
    try:
        yield
    finally:
        _restore_stdlib_logger(root, root_state)
        for name, candidate in logging.Logger.manager.loggerDict.items():
            if not isinstance(candidate, logging.Logger):
                continue
            if state := logger_states.get(name):
                _restore_stdlib_logger(candidate, state)
            else:
                candidate.handlers.clear()
                candidate.setLevel(logging.NOTSET)
                candidate.disabled = False
                candidate.propagate = True


@pytest.fixture(autouse=True)
def _restore_logger():
    # 전역 logging 상태를 다른 테스트로 흘리지 않도록 종료 후 복원한다.
    with _preserve_stdlib_logging():
        yield
    logger.remove()


def test_stdlib_logging_state_guard_restores_mutations():
    root = logging.getLogger()
    probe = logging.getLogger("test.fixture.logging_state")
    root_state = _stdlib_logger_state(root)
    probe_state = _stdlib_logger_state(probe)

    with _preserve_stdlib_logging():
        root.handlers.clear()
        root.setLevel(logging.ERROR)
        probe.addHandler(logging.NullHandler())
        probe.setLevel(logging.DEBUG)
        probe.disabled = True
        probe.propagate = False

    assert _stdlib_logger_state(root) == root_state
    assert _stdlib_logger_state(probe) == probe_state


def test_setup_logging_falls_back_to_console_when_path_unwritable(tmp_path, monkeypatch):
    # 일반 파일을 부모로 둔 경로 → mkdir(parents=True) 가 NotADirectoryError(OSError) 발생.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a dir")
    bad_path = blocker / "sub" / "app.log"

    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(bad_path))

    # 예외 없이 완료되어야 한다 (부팅 차단 방지).
    logger_module.setup_logging()

    assert not bad_path.exists()
    assert _handler_count() == 1


def test_setup_logging_adds_file_sink_when_path_writable(tmp_path, monkeypatch):
    good_path = tmp_path / "logs" / "app.log"
    good_path.parent.mkdir(mode=0o751)
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(good_path))

    logger_module.setup_logging()

    assert _handler_count() == 2
    assert stat.S_IMODE(good_path.parent.stat().st_mode) == 0o751
    assert stat.S_IMODE(good_path.stat().st_mode) == 0o600


def test_setup_logging_suppresses_raw_access_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "DEV")
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(tmp_path / "app.log"))
    logging.getLogger("httpx").disabled = True
    logging.getLogger("httpcore").disabled = True
    child_logger = logging.getLogger("httpcore.connection")
    child_logger.addHandler(logging.NullHandler())
    child_logger.propagate = False
    child_logger.disabled = True
    child_logger.setLevel(logging.INFO)

    logger_module.setup_logging()

    assert logging.getLogger("uvicorn.access").disabled is True
    # httpx/httpcore 는 자식 logger 상속 때문에 disabled 가 아니라 level 로 억제한다.
    # WARNING 이상(장애 신호)은 통과해야 하므로 disabled 여서는 안 된다.
    assert logging.getLogger("httpx").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpcore.connection").getEffectiveLevel() >= logging.WARNING
    assert logging.getLogger("httpx").disabled is False
    assert logging.getLogger("httpcore").disabled is False
    assert child_logger.handlers == []
    assert child_logger.propagate is True
    assert child_logger.disabled is False
    assert child_logger.level == logging.NOTSET


async def test_httpcore_info_is_suppressed_but_warning_reaches_safe_sink(
    tmp_path, monkeypatch,
):
    log_path = tmp_path / "httpcore.log"
    secret = "https://user:password@example.com/private-token"
    monkeypatch.setattr(settings, "ENVIRONMENT", "DEV")
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(log_path))
    logging.getLogger("httpcore").disabled = True
    child_logger = logging.getLogger("httpcore.connection")
    child_logger.addHandler(logging.NullHandler())
    child_logger.propagate = False
    child_logger.setLevel(logging.INFO)

    logger_module.setup_logging()

    child_logger.info("request %s", secret)
    child_logger.warning("transport failure %s", secret)
    await logger.complete()

    records = [
        json.loads(line)["record"]
        for line in log_path.read_text(encoding="utf-8").splitlines()
    ]
    client_records = [
        record for record in records
        if record["extra"].get("source_logger") == "httpcore.connection"
    ]
    assert len(client_records) == 1
    assert client_records[0]["level"]["name"] == "WARNING"
    assert client_records[0]["message"] == "Standard library log event"
    assert client_records[0]["extra"] == {
        "event": "stdlib_log",
        "source_logger": "httpcore.connection",
        "source_level": "WARNING",
    }
    assert secret not in repr(client_records[0])


def test_safe_logger_preserves_original_callsite():
    records = []
    sink_id = logger.add(lambda message: records.append(message.record))
    try:
        _emit_from_known_caller()
    finally:
        logger.remove(sink_id)

    assert records[-1]["function"] == "_emit_from_known_caller"
    assert records[-1]["name"] == __name__


def test_safe_logger_opt_and_log_cannot_bypass_privacy_gateway():
    records = []
    secret = "PRIVATE_OPT_LOG_7X9"
    sink_id = logger.add(lambda message: records.append(message.record.copy()))
    try:
        _emit_via_opt_and_log(secret)
    finally:
        logger.remove(sink_id)

    record = records[-1]
    assert secret not in str(record)
    assert record["message"] == "safe probe: RuntimeError"
    assert record["exception"] is None
    assert record["extra"]["error_type"] == "RuntimeError"
    assert record["function"] == "_emit_via_opt_and_log"


async def test_stdlib_exception_is_reduced_to_safe_metadata(tmp_path, monkeypatch):
    log_path = tmp_path / "stdlib-exception.log"
    secret = "PRIVATE_STDLIB_FRAME_VALUE_7X9"
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(log_path))
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    logger_module.setup_logging()

    try:
        _raise_private_frame(secret)
    except RuntimeError:
        logging.getLogger("app.stdlib").exception("safe stdlib failure")
    await logger.complete()

    raw_log = log_path.read_text(encoding="utf-8")
    assert secret not in raw_log
    record = json.loads(raw_log.splitlines()[-1])["record"]
    assert record["message"] == "Standard library log event"
    assert record["exception"] is None
    assert record["extra"]["event"] == "stdlib_log"
    assert record["extra"]["source_logger"] == "app.stdlib"
    assert record["extra"]["source_level"] == "ERROR"
    assert record["extra"]["error_type"] == "RuntimeError"
    assert record["extra"]["error_location"].endswith(":_raise_private_frame")


async def test_stdlib_exception_format_argument_is_sanitized(tmp_path, monkeypatch):
    log_path = tmp_path / "stdlib-argument.log"
    secret = "PRIVATE_STDLIB_ARGUMENT_7X9"
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(log_path))
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    logger_module.setup_logging()

    logging.getLogger("app.stdlib").error(
        "safe stdlib failure: %s", RuntimeError(secret)
    )
    await logger.complete()

    raw_log = log_path.read_text(encoding="utf-8")
    assert secret not in raw_log
    record = json.loads(raw_log.splitlines()[-1])["record"]
    assert record["message"] == "Standard library log event"
    assert record["extra"]["event"] == "stdlib_log"
    assert record["extra"]["source_logger"] == "app.stdlib"
    assert record["extra"]["error_type"] == "RuntimeError"


async def test_stdlib_arbitrary_message_payload_is_not_forwarded(tmp_path, monkeypatch):
    log_path = tmp_path / "stdlib-message.log"
    secret = "PRIVATE_STDLIB_MESSAGE_7X9"
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(log_path))
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    logger_module.setup_logging()

    logging.getLogger("app.stdlib").warning("unsafe vendor payload: %s", secret)
    await logger.complete()

    raw_log = log_path.read_text(encoding="utf-8")
    assert secret not in raw_log
    record = json.loads(raw_log.splitlines()[-1])["record"]
    assert record["message"] == "Standard library log event"
    assert record["extra"] == {
        "event": "stdlib_log",
        "source_logger": "app.stdlib",
        "source_level": "WARNING",
    }


async def test_rotated_file_sink_keeps_private_permissions(tmp_path, monkeypatch):
    log_path = tmp_path / "logs" / "app.log"
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(log_path))
    monkeypatch.setattr(settings, "LOG_ROTATION", "1 KB")

    logger_module.setup_logging()
    for _ in range(20):
        logger.info("x" * 200)
    await logger.complete()

    log_files = list(log_path.parent.glob("app*.log*"))
    assert len(log_files) >= 2
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in log_files)


async def test_setup_logging_strips_exception_payload_and_frame_values(
    tmp_path, monkeypatch,
):
    log_path = tmp_path / "logs" / "app.log"
    secret = "PRIVATE_FRAME_VALUE_7X9"
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(log_path))
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    logger_module.setup_logging()

    try:
        _raise_private_frame(secret)
    except RuntimeError:
        logger_module.get_logger("privacy.test").exception("safe failure")
    await logger.complete()

    raw_log = log_path.read_text(encoding="utf-8")
    record = json.loads(raw_log.splitlines()[-1])["record"]
    assert secret not in raw_log
    assert record["exception"] is None
    assert record["extra"]["error_type"] == "RuntimeError"
    assert record["extra"]["error_location"].endswith(":_raise_private_frame")


async def test_get_logger_replaces_exception_format_arguments(tmp_path, monkeypatch):
    log_path = tmp_path / "logs" / "app.log"
    secret = "PRIVATE_EXCEPTION_ARGUMENT_7X9"
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(log_path))
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    logger_module.setup_logging()

    logger_module.get_logger("privacy.test").error(
        "safe failure: {}", RuntimeError(secret)
    )
    await logger.complete()

    raw_log = log_path.read_text(encoding="utf-8")
    record = json.loads(raw_log.splitlines()[-1])["record"]
    assert secret not in raw_log
    assert record["message"] == "safe failure: RuntimeError"
    assert record["extra"]["error_type"] == "RuntimeError"


def test_setup_logging_tightens_existing_rotated_files(tmp_path, monkeypatch):
    log_path = tmp_path / "logs" / "app.log"
    log_path.parent.mkdir()
    archived_path = log_path.parent / "app.2026-01-01_00-00-00.log.gz"
    archived_path.write_bytes(b"old log")
    archived_path.chmod(0o644)
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(log_path))

    logger_module.setup_logging()

    assert stat.S_IMODE(archived_path.stat().st_mode) == 0o600


async def test_registration_success_file_log_does_not_contain_account_pii(
    tmp_path, monkeypatch,
):
    log_path = tmp_path / "logs" / "app.log"
    email = "private.person@example.com"
    user_id = "USER_private_123"
    service = AsyncMock(spec=RegisterService)
    cache = SimpleNamespace(set_flag=AsyncMock())
    request = Request({"type": "http", "state": {"user_id": user_id}})
    payload = RegisterRequest(
        email=email,
        user_name="비공개 사용자",
        phone_number="010-1234-5678",
        age=30,
        gender=Gender.FEMALE,
        nationality="korea",
        travel_styles=[],
    )

    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(log_path))
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    monkeypatch.setattr(register_router, "get_redis_cache_manager", lambda: cache)
    logger_module.setup_logging()

    response = await register_router.register(
        request=request,
        user_inform=payload,
        register_service=service,
    )
    await logger.complete()

    raw_log = log_path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in raw_log.splitlines()]
    registration_logs = [
        record for record in records
        if "2차 회원가입 완료" in record["record"]["message"]
    ]
    assert response.message == "회원가입이 완료되었습니다."
    assert len(registration_logs) == 1
    assert email not in raw_log
    assert user_id not in raw_log


async def test_client_error_file_log_uses_route_template_without_share_token(
    tmp_path, monkeypatch,
):
    log_path = tmp_path / "logs" / "app.log"
    share_token = "SECRET_SHARE_TOKEN_NOT_JWT"
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(log_path))
    monkeypatch.setattr(settings, "LOG_FORMAT", "json")
    logger_module.setup_logging()

    response = TestClient(create_app()).get(f"/api/public/share/plan/{share_token}")
    await logger.complete()

    raw_log = log_path.read_text(encoding="utf-8")
    records = [json.loads(line) for line in raw_log.splitlines()]
    client_errors = [
        record for record in records
        if record["record"]["extra"].get("event") == "http_client_error"
    ]
    extra = client_errors[0]["record"]["extra"]
    client_error_log = json.dumps(client_errors[0], ensure_ascii=False)
    assert response.status_code == 400
    assert len(client_errors) == 1
    assert share_token not in client_error_log
    assert extra["path"] == "/api/public/share/plan/{share_token}"
    assert extra["route"] == "/api/public/share/plan/{share_token}"
