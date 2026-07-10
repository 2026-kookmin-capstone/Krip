from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.chat.router.ws import _handle_read, _read_failed_event
from app.domain.chat.schema.ws_event import ReadOp


@pytest.mark.unit
async def test_handle_read_sends_ack_from_committed_service_result():
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    room_service = MagicMock()
    room_service.mark_read = AsyncMock(return_value=9)
    request = ReadOp(op="read", room_id="CR_1", up_to_server_seq=7)

    await _handle_read(
        websocket=websocket,
        session_id="WS_A",
        user_id="U_A",
        room_svc=room_service,
        req=request,
    )

    room_service.mark_read.assert_awaited_once_with(
        me_id="U_A",
        me_session_id="WS_A",
        room_id="CR_1",
        up_to_server_seq=7,
    )
    websocket.send_json.assert_awaited_once_with({
        "type": "read_ack",
        "room_id": "CR_1",
        "up_to_server_seq": 9,
    })


@pytest.mark.unit
async def test_handle_read_does_not_ack_when_post_commit_sync_fails():
    websocket = MagicMock()
    websocket.send_json = AsyncMock()
    room_service = MagicMock()
    room_service.mark_read = AsyncMock(side_effect=RuntimeError("redis publish failed"))
    request = ReadOp(op="read", room_id="CR_1", up_to_server_seq=7)

    with pytest.raises(RuntimeError, match="redis publish failed"):
        await _handle_read(
            websocket=websocket,
            session_id="WS_A",
            user_id="U_A",
            room_svc=room_service,
            req=request,
        )

    websocket.send_json.assert_not_awaited()


def test_read_failed_event_correlates_with_request_seq():
    request = ReadOp(op="read", room_id="CR_1", up_to_server_seq=7)

    assert _read_failed_event(request, "failed") == {
        "type": "read_failed",
        "room_id": "CR_1",
        "up_to_server_seq": 7,
        "reason": "failed",
    }
