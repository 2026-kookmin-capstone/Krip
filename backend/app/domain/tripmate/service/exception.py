"""Tripmate 도메인 커스텀 예외 — Router 가 HTTP status 로 매핑."""

from app.core.exception import NotFoundError


class TripmatePostNotFoundError(NotFoundError, ValueError):
    """미존재·숨김(비작성자)·차단 관계 — 존재 은닉으로 일원화. 404 매핑."""
