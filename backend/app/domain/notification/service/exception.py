"""알림 도메인 서비스 예외.

라우터 매핑:
    NotificationNotFoundError → 404
"""


class NotificationNotFoundError(Exception):
    """알림 미존재 또는 다른 유저 소유 — 정보 누출 회피로 일원화 (feed 도메인 패턴)."""
