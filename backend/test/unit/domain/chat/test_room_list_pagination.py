from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Request

from app.domain.chat.repository.chat_room import ChatRoomRepository
from app.domain.chat.router.room import list_rooms
from app.util.cursor import encode_cursor


@pytest.mark.unit
async def test_list_rooms_forwards_cursor():
    service = AsyncMock()
    service.list_rooms.return_value = SimpleNamespace(items=[], next_cursor=None)
    request = MagicMock(spec=Request)
    request.state = SimpleNamespace(user_id="U_A")

    response = await list_rooms(
        request=request,
        cursor="opaque-cursor",
        service=service,
    )

    assert response.items == []
    service.list_rooms.assert_awaited_once_with(
        me_id="U_A", cursor="opaque-cursor",
    )


@pytest.mark.unit
async def test_list_rooms_rejects_invalid_cursor():
    service = AsyncMock()
    service.list_rooms.side_effect = ValueError("유효하지 않은 커서입니다.")
    request = MagicMock(spec=Request)
    request.state = SimpleNamespace(user_id="U_A")

    with pytest.raises(HTTPException) as exc_info:
        await list_rooms(
            request=request,
            cursor="invalid",
            service=service,
        )

    assert exc_info.value.status_code == 400


@pytest.mark.unit
async def test_room_repository_rejects_naive_datetime_cursor():
    session = AsyncMock()
    repo = ChatRoomRepository(session)
    cursor = encode_cursor(datetime(2026, 7, 12), "CR_x")

    with pytest.raises(ValueError, match="유효하지 않은 커서"):
        await repo.find_rooms_of_user("U_A", cursor=cursor)

    session.execute.assert_not_awaited()
