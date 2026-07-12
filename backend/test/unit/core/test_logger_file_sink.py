"""setup_logging 파일 sink 실패 시 콘솔 전용 폴백 단위 테스트.

핵심 회귀 검증 (LOG_FILE_PATH 기본값이 컨테이너 절대경로라 로컬/CI 에서 mkdir 이
PermissionError/OSError 로 부팅을 막던 문제 수정):
    - 파일 sink 초기화가 실패해도 setup_logging 이 예외 없이 완료
    - 파일은 생성되지 않고 콘솔 sink 만 남음
    - 경로가 쓰기 가능하면(정상 케이스) 파일 sink 가 정상 등록됨
"""
import json
import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import Request
from loguru import logger

from app.config.setting import Settings, settings
from app.core import logger as logger_module
from app.domain.auth.model.user_detail_inform import Gender
from app.domain.auth.router import register as register_router
from app.domain.auth.schema.register import RegisterRequest
from app.domain.auth.service.register import RegisterService


def _handler_count() -> int:
    return len(logger._core.handlers)


def test_default_file_retention_matches_loki_window():
    assert Settings.model_fields["LOG_RETENTION"].default == "14 days"


@pytest.fixture(autouse=True)
def _restore_logger():
    # 전역 loguru 상태를 다른 테스트로 흘리지 않도록 종료 후 sink 를 정리한다.
    yield
    logger.remove()


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
