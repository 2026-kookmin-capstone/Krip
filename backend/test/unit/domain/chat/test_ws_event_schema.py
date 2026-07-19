"""WS 이벤트 스키마 검증 — SendOp 의 system 메시지 위조 차단."""
import pytest
from pydantic import ValidationError

from app.domain.chat.model.chat_message import MessageType
from app.domain.chat.schema.ws_event import (
    MessageBody,
    MessageNewEvent,
    ReadAckEvent,
    ReadFailedEvent,
    SendOp,
    ServerErrorEvent,
    UnreadSyncedEvent,
)


def test_server_error_defaults_to_non_retryable_and_accepts_correlation():
    default_event = ServerErrorEvent.model_validate({"type": "server_error"})
    assert default_event.retryable is False
    assert default_event.client_msg_id is None

    event = ServerErrorEvent(
        type="server_error",
        client_msg_id="CLIENT_1",
        retryable=True,
        reason="temporary",
    )
    assert event.client_msg_id == "CLIENT_1"
    assert event.retryable is True


@pytest.mark.unit
class TestSendOpTypeGuard:
    """클라가 보내는 send op 는 system 타입을 거부해야 한다 (unread/푸시 우회 스텔스 방지)."""

    def _kwargs(self, **override):
        base = dict(op="send", room_id="CR_1", client_msg_id="c1", content="hi")
        base.update(override)
        return base

    def test_defaults_to_text(self):
        op = SendOp(**self._kwargs())
        assert op.type == MessageType.TEXT

    def test_accepts_text_type(self):
        op = SendOp(**self._kwargs(type=MessageType.TEXT))
        assert op.type == MessageType.TEXT

    @pytest.mark.parametrize(
        "t", [MessageType.SYSTEM, MessageType.IMAGE, MessageType.FILE, "system", "image"],
    )
    def test_rejects_non_text_types(self, t):
        """SYSTEM 위조 차단 + 미구현 IMAGE/FILE fail-closed."""
        with pytest.raises(ValidationError):
            SendOp(**self._kwargs(type=t))

    def test_rejects_empty_content(self):
        """빈 메시지는 unread 증가·빈 FCM 푸시를 유발하므로 edit 과 동일하게 거부."""
        with pytest.raises(ValidationError):
            SendOp(**self._kwargs(content=""))


def test_read_ack_requires_request_correlation_separate_from_applied_watermark():
    with pytest.raises(ValidationError):
        ReadAckEvent.model_validate({
            "type": "read_ack",
            "room_id": "CR_1",
            "up_to_server_seq": 9,
        })

    event = ReadAckEvent(
        type="read_ack",
        room_id="CR_1",
        requested_up_to_server_seq=7,
        up_to_server_seq=9,
    )
    assert event.requested_up_to_server_seq == 7
    assert event.up_to_server_seq == 9


def test_read_failed_requires_request_seq():
    with pytest.raises(ValidationError):
        ReadFailedEvent(type="read_failed", room_id="CR_1", reason="failed")


def test_message_new_preserves_canonical_edit_delete_metadata():
    required = set(MessageBody.model_json_schema()["required"])
    assert {"edited_at", "deleted_at"} <= required

    event = MessageNewEvent(
        type="message.new",
        sender_session_id="WS_1",
        message=MessageBody(**{
            "message_id": "MSG_1",
            "chat_room_id": "CR_1",
            "server_seq": 1,
            "sender_id": "U_1",
            "type": "text",
            "content": None,
            "created_at": "2026-07-15T00:00:00+00:00",
            "edited_at": "2026-07-15T00:00:01+00:00",
            "deleted_at": "2026-07-15T00:00:02+00:00",
        }),
    )

    assert event.message.edited_at is not None
    assert event.message.deleted_at is not None


def test_unread_synced_defaults_optional_watermark_maps_to_empty():
    event = UnreadSyncedEvent(
        type="unread_synced", counts={"CR_1": 2},
    )

    assert event.watermarks == {}
    assert event.read_watermarks == {}
    assert event.model_dump()["watermarks"] == {}
    assert event.model_dump()["read_watermarks"] == {}


def test_unread_synced_preserves_explicit_watermark_maps():
    event = UnreadSyncedEvent(
        type="unread_synced",
        counts={"CR_1": 2},
        watermarks={"CR_1": 17},
        read_watermarks={"CR_1": 11},
    )

    assert event.watermarks == {"CR_1": 17}
    assert event.read_watermarks == {"CR_1": 11}
