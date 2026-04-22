"""MessageHistoryService 단위 테스트 (PHASE_2 #4 테스트 커버리지 보강).

페이징 경계값 (`has_more` / `next_cursor`), 권한 체크, soft-delete 된 메시지 content
마스킹까지 검증. Mongo/Redis/RDB 는 전부 mock.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.domain.chat.model.chat_room import ChatRoomType


NOW = datetime(2026, 4, 22, 12, 0, 0, tzinfo=timezone.utc)


def _mk_doc(
    message_id: str,
    server_seq: int,
    *,
    sender_id: str | None = "U_A",
    msg_type: str = "text",
    content=None,
    created_at: datetime = NOW,
    deleted_at: datetime | None = None,
    edited_at: datetime | None = None,
    chat_room_id: str = "CR_1",
) -> dict:
    return {
        "_id": message_id,
        "chat_room_id": chat_room_id,
        "server_seq": server_seq,
        "sender_id": sender_id,
        "type": msg_type,
        "content": "hi" if content is None else content,
        "created_at": created_at,
        "edited_at": edited_at,
        "deleted_at": deleted_at,
    }


def _mk_room(
    chat_room_id: str = "CR_1",
    *,
    type_: ChatRoomType = ChatRoomType.DIRECT,
    title: str | None = None,
    last_message_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        chat_room_id=chat_room_id,
        type=type_,
        title=title,
        last_message_id=last_message_id,
        last_message_server_seq=None,
        last_message_at=None,
        created_at=NOW,
        effective_last_at=NOW,
    )


# ──────────────────────────────────────────────────────────────────
# find_messages_before (위로 스크롤)
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestFindMessagesBefore:
    async def test_permission_error_when_not_active_member(
        self, service, chat_member_repo_mock,
    ):
        chat_member_repo_mock.is_active_member.return_value = False
        with pytest.raises(PermissionError):
            await service.find_messages_before(
                me_id="U_X", room_id="CR_1", before_server_seq=100, limit=10,
            )

    async def test_no_results(
        self, service, chat_member_repo_mock, message_repo_mock,
    ):
        chat_member_repo_mock.is_active_member.return_value = True
        message_repo_mock.find_before.return_value = []

        result = await service.find_messages_before(
            me_id="U_A", room_id="CR_1", before_server_seq=50, limit=10,
        )
        assert result.messages == []
        assert result.has_more is False
        assert result.next_cursor is None

    async def test_limit_exactly_no_more(
        self, service, chat_member_repo_mock, message_repo_mock,
    ):
        """limit=3 / 실제 조회 3건(limit+1=4 조회했으나 3개뿐) → has_more=False."""
        chat_member_repo_mock.is_active_member.return_value = True
        message_repo_mock.find_before.return_value = [
            _mk_doc("MSG_3", 3), _mk_doc("MSG_2", 2), _mk_doc("MSG_1", 1),
        ]

        result = await service.find_messages_before(
            me_id="U_A", room_id="CR_1", before_server_seq=10, limit=3,
        )
        assert len(result.messages) == 3
        assert result.has_more is False
        assert result.next_cursor is None

    async def test_limit_exceeded_has_more_and_cursor(
        self, service, chat_member_repo_mock, message_repo_mock,
    ):
        """limit=3, Mongo 에서 4건 반환 → has_more=True, next_cursor=3번째 seq (가장 오래된)."""
        chat_member_repo_mock.is_active_member.return_value = True
        message_repo_mock.find_before.return_value = [
            _mk_doc("MSG_6", 6), _mk_doc("MSG_5", 5),
            _mk_doc("MSG_4", 4), _mk_doc("MSG_3", 3),
        ]

        result = await service.find_messages_before(
            me_id="U_A", room_id="CR_1", before_server_seq=10, limit=3,
        )
        assert [m.server_seq for m in result.messages] == [6, 5, 4]
        assert result.has_more is True
        assert result.next_cursor == 4  # 마지막(=가장 오래된) seq

    async def test_deleted_message_content_is_masked(
        self, service, chat_member_repo_mock, message_repo_mock,
    ):
        chat_member_repo_mock.is_active_member.return_value = True
        message_repo_mock.find_before.return_value = [
            _mk_doc("MSG_1", 1, content="secret", deleted_at=NOW),
        ]

        result = await service.find_messages_before(
            me_id="U_A", room_id="CR_1", before_server_seq=10, limit=5,
        )
        assert result.messages[0].content is None  # 삭제된 메시지 마스킹
        assert result.messages[0].deleted_at == NOW


# ──────────────────────────────────────────────────────────────────
# find_messages_after (catch-up)
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestFindMessagesAfter:
    async def test_permission_error_when_not_active_member(
        self, service, chat_member_repo_mock,
    ):
        chat_member_repo_mock.is_active_member.return_value = False
        with pytest.raises(PermissionError):
            await service.find_messages_after(
                me_id="U_X", room_id="CR_1", after_server_seq=0, limit=200,
            )

    async def test_catch_up_ascending_with_has_more(
        self, service, chat_member_repo_mock, message_repo_mock,
    ):
        """after=0, limit=3, Mongo 에서 4건(ASC) 반환 → has_more=True, next_cursor=3번째 seq."""
        chat_member_repo_mock.is_active_member.return_value = True
        message_repo_mock.find_after.return_value = [
            _mk_doc("MSG_1", 1), _mk_doc("MSG_2", 2),
            _mk_doc("MSG_3", 3), _mk_doc("MSG_4", 4),
        ]

        result = await service.find_messages_after(
            me_id="U_A", room_id="CR_1", after_server_seq=0, limit=3,
        )
        assert [m.server_seq for m in result.messages] == [1, 2, 3]
        assert result.has_more is True
        assert result.next_cursor == 3  # 마지막(=가장 최신) seq — 클라는 다음 호출에 after=3

    async def test_no_more_messages_returns_empty(
        self, service, chat_member_repo_mock, message_repo_mock,
    ):
        """catch-up 완료 시 더 이상 메시지 없음 → 빈 배열 + has_more=False."""
        chat_member_repo_mock.is_active_member.return_value = True
        message_repo_mock.find_after.return_value = []

        result = await service.find_messages_after(
            me_id="U_A", room_id="CR_1", after_server_seq=999, limit=200,
        )
        assert result.messages == []
        assert result.has_more is False
        assert result.next_cursor is None


# ──────────────────────────────────────────────────────────────────
# list_rooms
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestListRooms:
    async def test_empty_when_no_rooms(
        self, service, chat_room_repo_mock, redis_mock,
    ):
        chat_room_repo_mock.find_rooms_of_user.return_value = []
        redis_mock.hgetall.return_value = {}

        result = await service.list_rooms(me_id="U_A")
        assert result.items == []
        assert result.next_cursor is None

    async def test_direct_room_with_peer_profile(
        self, service, chat_room_repo_mock, user_repo_mock, redis_mock,
        message_repo_mock,
    ):
        room = _mk_room(chat_room_id="CR_d", type_=ChatRoomType.DIRECT)
        chat_room_repo_mock.find_rooms_of_user.return_value = [(room, "U_B")]
        user_repo_mock.find_by_id_with_profile.return_value = SimpleNamespace(
            user_id="U_B",
            detail=SimpleNamespace(user_name="peer_name"),
        )
        redis_mock.hgetall.return_value = {"CR_d": "3"}
        message_repo_mock.find_by_ids.return_value = {}

        result = await service.list_rooms(me_id="U_A")
        assert len(result.items) == 1
        item = result.items[0]
        assert item.type == ChatRoomType.DIRECT
        assert item.peer.user_id == "U_B"
        assert item.peer.user_name == "peer_name"
        assert item.unread_count == 3
        assert item.last_message is None

    async def test_group_room_has_no_peer(
        self, service, chat_room_repo_mock, redis_mock, message_repo_mock,
    ):
        room = _mk_room(chat_room_id="CR_g", type_=ChatRoomType.GROUP, title="T")
        chat_room_repo_mock.find_rooms_of_user.return_value = [(room, None)]
        redis_mock.hgetall.return_value = {}
        message_repo_mock.find_by_ids.return_value = {}

        result = await service.list_rooms(me_id="U_A")
        assert result.items[0].type == ChatRoomType.GROUP
        assert result.items[0].title == "T"
        assert result.items[0].peer is None

    async def test_direct_peer_withdrawn_returns_null_profile(
        self, service, chat_room_repo_mock, redis_mock, message_repo_mock,
    ):
        """direct 방이지만 peer 가 탈퇴 → peer_user_id=None → peer 는 (None, None)."""
        room = _mk_room(chat_room_id="CR_orphan", type_=ChatRoomType.DIRECT)
        chat_room_repo_mock.find_rooms_of_user.return_value = [(room, None)]
        redis_mock.hgetall.return_value = {}
        message_repo_mock.find_by_ids.return_value = {}

        result = await service.list_rooms(me_id="U_A")
        assert result.items[0].peer.user_id is None
        assert result.items[0].peer.user_name is None

    async def test_last_message_preview_masks_deleted(
        self, service, chat_room_repo_mock, redis_mock, message_repo_mock,
    ):
        room = _mk_room(
            chat_room_id="CR_1", type_=ChatRoomType.GROUP, title="T",
            last_message_id="MSG_last",
        )
        chat_room_repo_mock.find_rooms_of_user.return_value = [(room, None)]
        redis_mock.hgetall.return_value = {}
        message_repo_mock.find_by_ids.return_value = {
            "MSG_last": _mk_doc(
                "MSG_last", 10, content="bye", deleted_at=NOW,
            )
        }

        result = await service.list_rooms(me_id="U_A")
        assert result.items[0].last_message is not None
        assert result.items[0].last_message.content is None  # 삭제 마스킹
        assert result.items[0].last_message.server_seq == 10


# ──────────────────────────────────────────────────────────────────
# get_unread_counts
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestGetUnreadCounts:
    async def test_maps_hgetall_to_int_dict(self, service, redis_mock):
        redis_mock.hgetall.return_value = {"CR_1": "5", "CR_2": "0"}
        result = await service.get_unread_counts(me_id="U_A")
        assert result == {"CR_1": 5, "CR_2": 0}

    async def test_empty_hash_returns_empty_dict(self, service, redis_mock):
        redis_mock.hgetall.return_value = {}
        result = await service.get_unread_counts(me_id="U_A")
        assert result == {}
