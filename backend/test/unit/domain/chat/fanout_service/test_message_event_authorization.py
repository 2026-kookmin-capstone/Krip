from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.domain.chat.schema.ws_event import MessageNewEvent
from app.domain.chat.service import fanout as fanout_module
from app.domain.chat.service.fanout import FanoutAuthorizationService


pytestmark = pytest.mark.unit


async def test_durable_message_revision_is_scoped_per_message(monkeypatch):
    docs = {
        "MSG_A": {
            "created_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
            "edited_at": datetime(2026, 7, 15, 0, 0, 2, tzinfo=timezone.utc),
            "deleted_at": None,
            "content": "a2",
        },
        "MSG_B": {
            "created_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
            "edited_at": datetime(2026, 7, 15, 0, 0, 1, tzinfo=timezone.utc),
            "deleted_at": None,
            "content": "b1",
        },
    }
    repository = MagicMock()
    repository.find_by_id = AsyncMock(side_effect=lambda message_id: docs.get(message_id))
    monkeypatch.setattr(fanout_module.mongodb, "database", MagicMock())
    monkeypatch.setattr(
        fanout_module, "ChatMessageRepository", lambda _database: repository,
    )
    authorization = FanoutAuthorizationService(MagicMock())

    assert await authorization.prepare_current_message_event({
        "type": "message.updated",
        "message_id": "MSG_A",
        "content": "a2",
        "edited_at": "2026-07-15T00:00:02+00:00",
    })
    assert await authorization.prepare_current_message_event({
        "type": "message.updated",
        "message_id": "MSG_B",
        "content": "b1",
        "edited_at": "2026-07-15T00:00:01+00:00",
    })


async def test_durable_tombstone_rejects_stale_edit_and_allows_retry(monkeypatch):
    deleted_at = datetime(2026, 7, 15, 0, 0, 2, tzinfo=timezone.utc)
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value={
        "created_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
        "edited_at": datetime(2026, 7, 15, 0, 0, 1, tzinfo=timezone.utc),
        "deleted_at": deleted_at,
        "content": None,
    })
    monkeypatch.setattr(fanout_module.mongodb, "database", MagicMock())
    monkeypatch.setattr(
        fanout_module, "ChatMessageRepository", lambda _database: repository,
    )
    authorization = FanoutAuthorizationService(MagicMock())

    assert not await authorization.prepare_current_message_event({
        "type": "message.updated",
        "message_id": "MSG_1",
        "content": "stale",
        "edited_at": "2026-07-15T00:00:01+00:00",
    })
    tombstone = {
        "type": "message.deleted",
        "message_id": "MSG_1",
        "deleted_at": "2026-07-15T00:00:02+00:00",
    }
    assert await authorization.prepare_current_message_event(tombstone)
    assert await authorization.prepare_current_message_event(tombstone)


async def test_delayed_new_is_rewritten_from_current_durable_state(monkeypatch):
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value={
        "created_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
        "edited_at": datetime(2026, 7, 15, 0, 0, 1, tzinfo=timezone.utc),
        "deleted_at": None,
        "content": "current",
    })
    monkeypatch.setattr(fanout_module.mongodb, "database", MagicMock())
    monkeypatch.setattr(
        fanout_module, "ChatMessageRepository", lambda _database: repository,
    )
    authorization = FanoutAuthorizationService(MagicMock())
    payload = {
        "type": "message.new",
        "message": {
            "message_id": "MSG_1",
            "created_at": "2026-07-15T00:00:00+00:00",
            "content": "stale",
        },
    }

    assert await authorization.prepare_current_message_event(payload)
    assert payload["message"]["content"] == "current"
    assert payload["message"]["edited_at"] == "2026-07-15T00:00:01+00:00"


async def test_message_event_cannot_cross_room_and_tombstone_is_canonical(monkeypatch):
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value={
        "chat_room_id": "CR_A",
        "created_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
        "edited_at": None,
        "deleted_at": datetime(2026, 7, 15, 0, 0, 2, tzinfo=timezone.utc),
        "content": None,
    })
    monkeypatch.setattr(fanout_module.mongodb, "database", MagicMock())
    monkeypatch.setattr(
        fanout_module, "ChatMessageRepository", lambda _database: repository,
    )
    authorization = FanoutAuthorizationService(MagicMock())
    payload = {
        "type": "message.deleted",
        "message_id": "MSG_1",
        "deleted_at": "2026-07-15T00:00:02+00:00",
        "content": "secret",
    }

    assert not await authorization.prepare_current_message_event(
        payload.copy(), room_id="CR_B",
    )
    assert await authorization.prepare_current_message_event(payload, room_id="CR_A")
    assert "content" not in payload


async def test_bson_millisecond_timestamp_roundtrip_is_current(monkeypatch):
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value={
        "chat_room_id": "CR_1",
        "created_at": datetime(2026, 7, 15, 0, 0, 0, 123000, tzinfo=timezone.utc),
        "edited_at": None,
        "deleted_at": None,
        "content": "current",
    })
    monkeypatch.setattr(fanout_module.mongodb, "database", MagicMock())
    monkeypatch.setattr(
        fanout_module, "ChatMessageRepository", lambda _database: repository,
    )
    authorization = FanoutAuthorizationService(MagicMock())
    payload = {
        "type": "message.new",
        "message": {
            "message_id": "MSG_1",
            "chat_room_id": "CR_1",
            "created_at": "2026-07-15T00:00:00.123456+00:00",
            "content": "current",
        },
    }

    assert await authorization.prepare_current_message_event(payload, room_id="CR_1")


async def test_canonical_system_message_satisfies_wire_schema(monkeypatch):
    repository = MagicMock()
    repository.find_by_id = AsyncMock(return_value={
        "chat_room_id": "CR_1",
        "server_seq": 7,
        "sender_id": None,
        "type": "system",
        "content": {"action": "leave"},
        "created_at": datetime(2026, 7, 15, tzinfo=timezone.utc),
        "edited_at": None,
        "deleted_at": None,
    })
    monkeypatch.setattr(fanout_module.mongodb, "database", MagicMock())
    monkeypatch.setattr(
        fanout_module, "ChatMessageRepository", lambda _database: repository,
    )
    authorization = FanoutAuthorizationService(MagicMock())
    payload = {
        "type": "message.new",
        "sender_session_id": None,
        "message": {
            "message_id": "MSG_SYS",
            "created_at": "2026-07-15T00:00:00+00:00",
        },
    }

    assert await authorization.prepare_current_message_event(payload, room_id="CR_1")
    assert MessageNewEvent.model_validate(payload).sender_session_id == ""
