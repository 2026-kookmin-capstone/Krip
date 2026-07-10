"""인박스 라우터 계약 — 자동 읽음 마킹이 전 페이지에서 수행되는지.

regression: 라우터가 첫 페이지(cursor 미지정)에서만 mark_as_read 하면, 20건 초과 미읽음
유저의 '더 보기' 페이지 항목이 영구 미읽음으로 남아 뱃지가 안 빠진다. 마킹은 service 가
페이지 id 로 한정하므로 전 페이지 마킹이 안전하다.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.domain.notification.dto.inbox import InboxListData
from app.domain.notification.router.inbox import list_inbox


pytestmark = pytest.mark.unit


def _request(user_id="U_a"):
    return SimpleNamespace(state=SimpleNamespace(user_id=user_id))


class TestListInboxMarksAllPages:
    async def test_first_page_marks_read(self):
        service = AsyncMock()
        service.list_items.return_value = InboxListData(items=[], next_cursor=None)

        await list_inbox(request=_request(), cursor=None, service=service)

        assert service.list_items.await_args.kwargs["mark_as_read"] is True

    async def test_load_more_page_also_marks_read(self):
        """cursor 가 있어도(=더 보기) mark_as_read=True — 뱃지 stuck 회귀 방지."""
        service = AsyncMock()
        service.list_items.return_value = InboxListData(items=[], next_cursor=None)

        await list_inbox(request=_request(), cursor="opaque-token", service=service)

        assert service.list_items.await_args.kwargs["mark_as_read"] is True
