"""인박스 도메인 서비스 예외.

라우터 매핑:
    InboxItemNotFoundError → 404
"""


class InboxItemNotFoundError(Exception):
    """인박스 항목 미존재 또는 다른 유저 소유 — 정보 누출 회피로 일원화 (feed 도메인 패턴)."""
