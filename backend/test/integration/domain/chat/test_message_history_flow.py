"""MessageHistoryService 통합 테스트 (PHASE_2 #4).

실제 Mongo 에 여러 건의 메시지를 쓴 뒤 `before_server_seq` / `after_server_seq`
페이징 규약이 정확히 동작하는지 검증. catch-up 경로(`after`) 가 ASC 로 정렬되어
next_cursor 를 따라가며 누락 없이 전부 내려오는지도 확인.
"""

from datetime import datetime, timezone

import pytest
import pytest_asyncio

from app.domain.chat.dto.message import MessageListData
from app.domain.chat.model.chat_message import MessageType
from app.domain.chat.model.chat_room import ChatRoom, ChatRoomType
from app.domain.chat.model.chat_room_member import ChatRoomMember
from app.domain.chat.repository.chat_room import ChatRoomRepository
from app.domain.chat.service.message_history import MessageHistoryService
from app.domain.chat.service.room import RoomService
from app.domain.friend.model.friendship import Friendship, FriendshipStatus
from app.util.cursor import encode_cursor


pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seed_friendship(session_factory):
    async def _seed(user_a: str, user_b: str) -> None:
        async with session_factory() as s:
            s.add(Friendship(
                requester_id=user_a,
                addressee_id=user_b,
                status=FriendshipStatus.ACCEPTED,
            ))
            await s.commit()
    return _seed


@pytest_asyncio.fixture
async def room_with_messages(
    uow, seed_users, seed_friendship, chat_fanout_stub, message_service,
    patch_external_clients,
):
    """그룹 방 + 실제 `send_message` 호출로 N 건 적재한 픽스처.

    방 생성 시 `system message (created)` 가 자동 기록되므로 그 뒤에 text 메시지 N 건.
    반환: (room_id, user_a, user_b, text_seqs) — text 메시지의 server_seq 리스트 (오름차순)
    """
    a, b, _ = await seed_users(3)
    await seed_friendship(a, b)

    room_svc = RoomService(
        uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
    )
    room = await room_svc.create_group_room(me_id=a, title="hist", member_ids=[b])
    room_id = room.chat_room_id

    text_seqs: list[int] = []
    for i in range(10):
        ack = await message_service.send_message(
            sender_user_id=a,
            sender_session_id=f"WS_A_{i}",
            room_id=room_id,
            client_msg_id=f"cm-{i}",
            msg_type=MessageType.TEXT,
            content=f"msg {i}",
        )
        text_seqs.append(ack.server_seq)

    return room_id, a, b, text_seqs


class TestFindMessagesBeforeFlow:
    async def test_paginates_desc_with_has_more(
        self, uow, room_with_messages, patch_external_clients,
    ):
        room_id, a, b, text_seqs = room_with_messages
        history = MessageHistoryService(uow=uow)

        page1: MessageListData = await history.find_messages_before(
            me_id=a, room_id=room_id, before_server_seq=10_000_000, limit=5,
        )
        assert len(page1.messages) == 5
        assert page1.has_more is True
        assert page1.next_cursor == page1.messages[-1].server_seq
        seqs1 = [m.server_seq for m in page1.messages]
        assert seqs1 == sorted(seqs1, reverse=True)

        page2 = await history.find_messages_before(
            me_id=a, room_id=room_id, before_server_seq=page1.next_cursor, limit=5,
        )
        assert len(page2.messages) <= 6
        if page2.has_more:
            page3 = await history.find_messages_before(
                me_id=a, room_id=room_id, before_server_seq=page2.next_cursor, limit=10,
            )
            assert page3.has_more is False

        combined = [m.server_seq for m in (page1.messages + page2.messages)]
        assert len(combined) == len(set(combined)), "페이지 간 중복 발생"

    async def test_empty_room_returns_empty_page(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, message_service,
        patch_external_clients,
    ):
        a, b, _ = await seed_users(3)
        await seed_friendship(a, b)
        room_svc = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await room_svc.create_group_room(me_id=a, title="empty", member_ids=[b])

        history = MessageHistoryService(uow=uow)
        result = await history.find_messages_before(
            me_id=a, room_id=room.chat_room_id, before_server_seq=0, limit=10,
        )
        assert result.messages == []
        assert result.has_more is False
        assert result.next_cursor is None


class TestFindMessagesAfterFlow:
    async def test_catch_up_returns_ascending_up_to_limit(
        self, uow, room_with_messages, patch_external_clients,
    ):
        room_id, a, _, text_seqs = room_with_messages
        history = MessageHistoryService(uow=uow)

        page1 = await history.find_messages_after(
            me_id=a, room_id=room_id, after_server_seq=0, limit=5,
        )
        assert len(page1.messages) == 5
        seqs1 = [m.server_seq for m in page1.messages]
        assert seqs1 == sorted(seqs1)
        assert page1.has_more is True
        assert page1.next_cursor == seqs1[-1]

        collected = list(seqs1)
        cursor = page1.next_cursor
        safety = 0
        while cursor is not None and safety < 5:
            nxt = await history.find_messages_after(
                me_id=a, room_id=room_id, after_server_seq=cursor, limit=5,
            )
            collected.extend(m.server_seq for m in nxt.messages)
            cursor = nxt.next_cursor
            safety += 1

        for seq in text_seqs:
            assert seq in collected, f"catch-up 에서 seq={seq} 누락"
        assert len(collected) == len(set(collected))

    async def test_after_beyond_max_returns_empty(
        self, uow, room_with_messages, patch_external_clients,
    ):
        """catch-up 이 완료된 상태에서 다시 호출 → 빈 배열 + has_more=False."""
        room_id, a, _, text_seqs = room_with_messages
        history = MessageHistoryService(uow=uow)

        result = await history.find_messages_after(
            me_id=a, room_id=room_id, after_server_seq=max(text_seqs) + 100, limit=200,
        )
        assert result.messages == []
        assert result.has_more is False
        assert result.next_cursor is None


class TestPermissionFlow:
    async def test_non_member_cannot_read(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, message_service,
        patch_external_clients,
    ):
        a, b, c = await seed_users(3)
        await seed_friendship(a, b)

        room_svc = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await room_svc.create_group_room(me_id=a, title="T", member_ids=[b])

        history = MessageHistoryService(uow=uow)
        with pytest.raises(PermissionError):
            await history.find_messages_before(
                me_id=c, room_id=room.chat_room_id, before_server_seq=999, limit=10,
            )
        with pytest.raises(PermissionError):
            await history.find_messages_after(
                me_id=c, room_id=room.chat_room_id, after_server_seq=0, limit=10,
            )

    async def test_left_member_cannot_read(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, message_service,
        patch_external_clients,
    ):
        a, b, _ = await seed_users(3)
        await seed_friendship(a, b)
        room_svc = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await room_svc.create_group_room(me_id=a, title="T", member_ids=[b])
        await room_svc.leave_room(me_id=b, room_id=room.chat_room_id)

        history = MessageHistoryService(uow=uow)
        with pytest.raises(PermissionError):
            await history.find_messages_before(
                me_id=b, room_id=room.chat_room_id, before_server_seq=999, limit=10,
            )


class TestListRoomsFlow:
    async def test_501st_room_is_reachable_via_service_cursor(
        self, uow, session_factory, seed_users, redis_hot, patch_external_clients,
    ):
        service = MessageHistoryService(uow)
        user_id, *_ = await seed_users(3)
        created_at = datetime(2026, 7, 12, tzinfo=timezone.utc)
        room_ids = [f"CR_page_{index:04d}" for index in range(501)]

        async with session_factory() as session:
            session.add_all([
                ChatRoom(
                    chat_room_id=room_id,
                    type=ChatRoomType.GROUP,
                    title=room_id,
                    creator_id=user_id,
                    created_at=created_at,
                )
                for room_id in room_ids
            ])
            session.add_all([
                ChatRoomMember(
                    chat_room_id=room_id,
                    user_id=user_id,
                    joined_at=created_at,
                    is_left=False,
                    notification_muted=False,
                )
                for room_id in room_ids
            ])
            await session.commit()

        first = await service.list_rooms(user_id)
        second = await service.list_rooms(user_id, cursor=first.next_cursor)

        assert len(first.items) == 500
        assert first.next_cursor is not None
        assert len(second.items) == 1
        assert second.next_cursor is None
        assert {
            room.chat_room_id for room in [*first.items, *second.items]
        } == set(room_ids)

    async def test_keyset_paginates_identical_effective_timestamp_without_gaps(
        self, session_factory, seed_users,
    ):
        user_id, *_ = await seed_users(3)
        at = datetime(2026, 7, 12, 12, 0, tzinfo=timezone.utc)
        room_ids = [f"CR_page_{i}" for i in range(5)]

        async with session_factory() as session:
            session.add_all([
                ChatRoom(
                    chat_room_id=room_id,
                    type=ChatRoomType.GROUP,
                    title=room_id,
                    creator_id=user_id,
                    created_at=at,
                )
                for room_id in room_ids
            ])
            session.add_all([
                ChatRoomMember(
                    chat_room_id=room_id,
                    user_id=user_id,
                    is_left=False,
                )
                for room_id in room_ids
            ])
            await session.commit()

        seen: list[str] = []
        cursor = None
        async with session_factory() as session:
            repo = ChatRoomRepository(session)
            while True:
                rows = await repo.find_rooms_of_user(
                    user_id, cursor=cursor, limit=2,
                )
                if not rows:
                    break
                seen.extend(room.chat_room_id for room, _, _ in rows)
                last_room = rows[-1][0]
                cursor = encode_cursor(
                    last_room.effective_last_at,
                    last_room.chat_room_id,
                )

        assert seen == sorted(room_ids, reverse=True)
        assert len(seen) == len(set(seen))

    async def test_includes_last_message_preview_and_unread(
        self, uow, room_with_messages, redis_hot, patch_external_clients,
    ):
        room_id, a, b, text_seqs = room_with_messages
        history = MessageHistoryService(uow=uow)

        result = await history.list_rooms(me_id=a)
        assert len(result.items) == 1
        item = result.items[0]
        assert item.chat_room_id == room_id
        assert item.title == "hist"
        assert item.unread_count == 0
        assert item.last_message is not None
        assert item.last_message.server_seq == max(text_seqs)
