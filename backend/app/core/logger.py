"""로깅 설정 (loguru)

환경변수:
  LOG_LEVEL       최소 출력 레벨 (TRACE<DEBUG<INFO<SUCCESS<WARNING<ERROR<CRITICAL)
  LOG_FORMAT      "json"(수집/분석용) | "console"(로컬 디버깅용). PROD 는 항상 json 강제.
  LOG_FILE_PATH   None 이면 콘솔만, 경로 지정 시 파일에도 기록
  LOG_ROTATION    "100 MB" 등 용량/시간 기준으로 롤테이션 (loguru 규칙)
  LOG_RETENTION   "30 days" 등 경과 후 자동 삭제
  LOG_COMPRESSION "gz" 등 롤테이션 파일 압축

사용:
  logger = get_logger("service_name")
  logger.bind(user_id=123).info("서비스 완료")

포맷팅: f-string 대신 loguru {} 포맷을 써 레벨 비활성 시 문자열 조합을 생략한다.
  logger.info("유저: {}", user_id)      # (O)
  logger.info(f"유저: {user_id}")       # (X) 항상 평가됨
"""
import logging
import sys
from pathlib import Path

from loguru import logger
from loguru._logger import Logger

from app.config.setting import settings


def setup_logging() -> None:
    """로깅 시스템 설정"""

    # PROD + console 포맷은 Promtail JSON parser 를 깨뜨리므로 json 으로 강제한다.
    # 발화 알림은 sink 가 준비된 함수 끝에서 emit (remove~add 사이엔 sink 부재).
    requested_format = settings.LOG_FORMAT
    forced_json = settings.is_production and requested_format != "json"
    log_format = "json" if forced_json else requested_format

    logger.remove()

    # 콘솔 출력
    if log_format == "json":
        logger.add(
            sys.stdout,
            format="{message}",
            serialize=True,
            level=settings.LOG_LEVEL,
            enqueue=True
        )
    else:
        logger.add(
            sys.stdout,
            format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level> | {extra}",
            level=settings.LOG_LEVEL,
            colorize=True,
            enqueue=True
        )

    # 파일 출력
    # LOG_FILE_PATH 기본값이 컨테이너 절대경로라 로컬/CI 에서 mkdir 이 OSError 로 부팅을 막을 수 있음.
    if settings.LOG_FILE_PATH:
        try:
            log_path = Path(settings.LOG_FILE_PATH)
            log_path.parent.mkdir(parents=True, exist_ok=True)

            logger.add(
                settings.LOG_FILE_PATH,
                rotation=settings.LOG_ROTATION,
                retention=settings.LOG_RETENTION,
                compression=settings.LOG_COMPRESSION,
                format="{message}",
                serialize=True,
                level=settings.LOG_LEVEL,
                encoding="utf-8",
                enqueue=True
            )
        except OSError as e:
            # 이미 등록된 콘솔 sink 로 경고만 남기고 파일 sink 없이 진행 (부팅 차단 방지).
            logger.warning(
                "LOG_FILE_PATH={} 파일 sink 초기화 실패({}) — 콘솔 출력만으로 계속합니다.",
                settings.LOG_FILE_PATH,
                e,
            )
    
    # 표준 logging 을 loguru 로 흘려보내는 핸들러
    class InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                level = logger.level(record.levelname).name
            except ValueError:
                level = record.levelno

            # logging 내부 프레임을 건너뛰어 실제 호출 지점의 depth 를 찾는다.
            frame, depth = logging.currentframe(), 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())

    logging.basicConfig(handlers=[InterceptHandler()], level=0, force=True)

    # uvicorn CLI 는 자기 로거에 plain-text 핸들러를 propagate=False 로 심는다.
    # basicConfig(force=True) 는 root 만 건드리므로 그대로 두면 JSON stdout 에
    # plain-text 가 섞여 Promtail 이 깨진다. 핸들러를 비우고 propagate 를 살려
    # loguru 단일 경로로 통합한다.
    for _name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        _uvicorn_logger = logging.getLogger(_name)
        _uvicorn_logger.handlers.clear()
        _uvicorn_logger.propagate = True

    logging.getLogger("uvicorn").setLevel(logging.INFO)
    # PROD 는 per-request 접근 로그를 억제(RED 메트릭이 대체) — WARNING 으로 INFO drop.
    # DEV 는 디버깅용으로 노출.
    logging.getLogger("uvicorn.access").setLevel(
        logging.WARNING if settings.is_production else logging.INFO
    )
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    # json 강제 알림 — 운영자가 .env 에 박은 원래 값(requested_format)을 보여준다.
    if forced_json:
        logger.warning(
            "PROD 환경에서 LOG_FORMAT={} 가 지정되어 있어 json 으로 강제 변환했습니다. "
            "Promtail JSON parser 호환 보호.",
            requested_format,
        )

    logger.info("Logging system initialized with level: {}", settings.LOG_LEVEL)


def get_logger(name: str) -> Logger:
    """이름이 지정된 로거 가져오기"""
    return logger.bind(logger_name=name)


# 전역 로거 인스턴스
app_logger = get_logger("app")