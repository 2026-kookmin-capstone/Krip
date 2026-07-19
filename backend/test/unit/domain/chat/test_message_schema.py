import pytest
from pydantic import ValidationError

from app.domain.chat.schema.message import ChatMessageResponse


def _message(**overrides):
    payload = {
        "message_id": "MSG_1",
        "chat_room_id": "ROOM_1",
        "server_seq": 1,
        "type": "text",
        "created_at": "2026-01-01T00:00:00Z",
        "edited_at": None,
        "deleted_at": None,
    }
    payload.update(overrides)
    return payload


def test_message_revision_fields_are_required_but_nullable():
    message = ChatMessageResponse(**_message())
    assert message.edited_at is None
    assert message.deleted_at is None

    required = set(ChatMessageResponse.model_json_schema()["required"])
    assert {"edited_at", "deleted_at"} <= required

    from app.main import app

    mounted_required = set(
        app.openapi()["components"]["schemas"]["ChatMessageResponse"]["required"]
    )
    assert {"edited_at", "deleted_at"} <= mounted_required

    for field in ("edited_at", "deleted_at"):
        payload = _message()
        del payload[field]
        with pytest.raises(ValidationError):
            ChatMessageResponse(**payload)