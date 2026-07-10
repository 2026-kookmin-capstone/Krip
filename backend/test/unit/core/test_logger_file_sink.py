"""setup_logging 파일 sink 실패 시 콘솔 전용 폴백 단위 테스트.

핵심 회귀 검증 (LOG_FILE_PATH 기본값이 컨테이너 절대경로라 로컬/CI 에서 mkdir 이
PermissionError/OSError 로 부팅을 막던 문제 수정):
    - 파일 sink 초기화가 실패해도 setup_logging 이 예외 없이 완료
    - 파일은 생성되지 않고 콘솔 sink 만 남음
    - 경로가 쓰기 가능하면(정상 케이스) 파일 sink 가 정상 등록됨
"""
import pytest
from loguru import logger

from app.config.setting import settings
from app.core import logger as logger_module


def _handler_count() -> int:
    return len(logger._core.handlers)


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

    # 파일 sink 는 등록되지 않아 파일이 만들어지지 않는다.
    assert not bad_path.exists()
    # 콘솔 sink 만 남는다.
    assert _handler_count() == 1


def test_setup_logging_adds_file_sink_when_path_writable(tmp_path, monkeypatch):
    good_path = tmp_path / "logs" / "app.log"
    monkeypatch.setattr(settings, "LOG_FILE_PATH", str(good_path))

    logger_module.setup_logging()

    # 콘솔 + 파일 sink 2개가 등록된다.
    assert _handler_count() == 2
    assert good_path.parent.is_dir()
