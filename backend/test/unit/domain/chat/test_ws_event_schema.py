"""WS 이벤트 스키마 검증 — SendOp 의 system 메시지 위조 차단."""
import pytest
from pydantic import ValidationError

from app.domain.chat.model.chat_message import MessageType
from app.domain.chat.schema.ws_event import ReadFailedEvent, SendOp


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

    @pytest.mark.parametrize("t", [MessageType.TEXT, MessageType.IMAGE, MessageType.FILE])
    def test_accepts_non_system_types(self, t):
        op = SendOp(**self._kwargs(type=t))
        assert op.type == t

    def test_rejects_system_enum(self):
        with pytest.raises(ValidationError):
            SendOp(**self._kwargs(type=MessageType.SYSTEM))

    def test_rejects_system_string(self):
        with pytest.raises(ValidationError):
            SendOp(**self._kwargs(type="system"))


def test_read_failed_requires_request_seq():
    with pytest.raises(ValidationError):
        ReadFailedEvent(type="read_failed", room_id="CR_1", reason="failed")
