"""도메인 예외 계층 — 전역 핸들러 매핑과 하위 호환(다중 상속) 검증."""
from unittest.mock import MagicMock

import pytest

from app.core.exception import ConflictError, DomainError, ForbiddenError, NotFoundError
from app.domain.auth.service.exception import (
    ProfileImageAlreadyExistsError,
    ProfileImageNotFoundError,
)
from app.domain.chat.service.exception import ChatRoomNotFoundError
from app.domain.feed.service.exception import FeedBlockedError, FeedNotFoundError
from app.domain.friend.service.friend_detail import UserNotFoundError
from app.domain.notification.service.exception import InboxItemNotFoundError
from app.middleware.tracking import handle_domain_error


pytestmark = pytest.mark.unit


class TestHierarchy:
    def test_not_found_family_maps_to_404(self):
        for exc_type in (
            FeedNotFoundError, ChatRoomNotFoundError, UserNotFoundError,
            InboxItemNotFoundError, ProfileImageNotFoundError,
        ):
            assert issubclass(exc_type, NotFoundError)
            assert exc_type.status_code == 404

    def test_status_codes_by_base(self):
        assert FeedBlockedError.status_code == 403
        assert ProfileImageAlreadyExistsError.status_code == 409
        assert issubclass(ForbiddenError, DomainError)
        assert issubclass(ConflictError, DomainError)

    def test_legacy_except_clauses_still_catch(self):
        """기존 라우터의 except ValueError / except PermissionError 하위 호환."""
        assert issubclass(FeedNotFoundError, ValueError)
        assert issubclass(InboxItemNotFoundError, ValueError)
        assert issubclass(FeedBlockedError, PermissionError)

    def test_chat_error_kind_preserved(self):
        """WS instrumentation 이 읽는 error_kind 속성 보존."""
        assert ChatRoomNotFoundError.error_kind == "not_found"


class TestHandler:
    async def test_handler_uses_declared_status_and_message(self):
        response = await handle_domain_error(
            MagicMock(), FeedNotFoundError("존재하지 않는 게시물입니다."),
        )
        assert response.status_code == 404
        assert "존재하지 않는 게시물입니다." in response.body.decode()

    async def test_inbox_not_found_no_longer_leaks_500(self):
        """C3 회귀 — InboxItemNotFoundError 가 핸들러에서 404 로 매핑된다."""
        response = await handle_domain_error(
            MagicMock(), InboxItemNotFoundError("존재하지 않는 인박스 항목입니다."),
        )
        assert response.status_code == 404
