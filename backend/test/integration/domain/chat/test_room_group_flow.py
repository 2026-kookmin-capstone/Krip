"""RoomService 그룹 방 통합 테스트 (PHASE_2 #1 + #2).

실제 Postgres + Redis + Mongo 를 엮어 생성/초대/퇴장/강퇴의 RDB+Redis+Mongo 부수효과
및 시스템 메시지 타임라인 기록까지 검증한다. `chat_fanout_stub` / `message_service` 는
상위 conftest 의 fixture 재사용 (같은 fanout 인스턴스를 RoomService 와 MessageService 가
공유해야 호출 카운트 일관).
"""
import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.chat.redis_key import room_members_key, room_seq_key, unread_key
from app.database.session import UnitOfWork
from app.domain.chat.model.chat_message import MessageType
from app.domain.chat.model.chat_room import ChatRoom, ChatRoomType
from app.domain.chat.model.chat_room_member import ChatRoomMember
from app.domain.chat.repository.chat_member import ChatRoomMemberRepository
from app.domain.chat.repository.chat_message import ChatMessageRepository
from app.domain.chat.service.message import MessageService
from app.domain.chat.service.room import RoomService
from app.domain.friend.model.friendship import Friendship, FriendshipStatus


pytestmark = pytest.mark.integration


# ──────────────────────────────────────────────────────────────────
# 공통 fixture
# ──────────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def seed_friendship(session_factory):
    """두 유저를 ACCEPTED 상태 친구로 맺어주는 팩토리."""
    async def _seed(user_a: str, user_b: str) -> None:
        async with session_factory() as s:
            s.add(Friendship(
                requester_id=user_a,
                addressee_id=user_b,
                status=FriendshipStatus.ACCEPTED,
            ))
            await s.commit()
    return _seed


# ──────────────────────────────────────────────────────────────────
# create_group_room
# ──────────────────────────────────────────────────────────────────

class TestCreateGroupRoomFlow:
    async def test_creates_room_with_members_and_caches(
        self, uow, seed_users, seed_friendship, chat_fanout_stub,
        session_factory, redis_hot, patch_external_clients, message_service,
    ):
        a, b, c = await seed_users(3)
        await seed_friendship(a, b)
        await seed_friendship(a, c)

        service = RoomService(uow=uow, fanout_service=chat_fanout_stub, message_service=message_service)
        dto = await service.create_group_room(
            me_id=a, title="캡스톤 7팀", member_ids=[b, c],
        )

        assert dto.type == ChatRoomType.GROUP
        assert dto.title == "캡스톤 7팀"
        assert dto.peer is None

        # RDB — chat_room + members 3건
        async with session_factory() as s:
            rooms = (await s.execute(select(ChatRoom))).scalars().all()
            members = (await s.execute(select(ChatRoomMember))).scalars().all()
            assert len(rooms) == 1
            assert rooms[0].creator_id == a
            assert rooms[0].direct_user_a_id is None
            assert rooms[0].direct_user_b_id is None
            assert len(members) == 3
            assert {m.user_id for m in members} == {a, b, c}
            assert all(not m.is_left for m in members)
            assert all(m.last_read_message_server_seq is None for m in members)

        # Redis — room:members 캐시에 3명 + unread 초기화
        cached = await redis_hot.smembers(room_members_key(dto.chat_room_id))
        assert cached == {a, b, c}
        for uid in (a, b, c):
            raw = await redis_hot.hget(unread_key(uid), dto.chat_room_id)
            assert raw == "0"

        # fan-out — 전원에게 room_joined
        assert chat_fanout_stub.fan_out_to_user.await_count == 3
        targets = {call.args[0] for call in chat_fanout_stub.fan_out_to_user.call_args_list}
        assert targets == {a, b, c}
        for call in chat_fanout_stub.fan_out_to_user.call_args_list:
            assert call.args[1]["type"] == "room_joined"
            assert call.args[1]["room_id"] == dto.chat_room_id

    async def test_non_friend_target_raises(
        self, uow, seed_users, chat_fanout_stub, patch_external_clients, message_service,
    ):
        a, b, _ = await seed_users(3)
        # friendship 맺지 않음
        service = RoomService(uow=uow, fanout_service=chat_fanout_stub, message_service=message_service)
        with pytest.raises(ValueError, match="친구가 아닌"):
            await service.create_group_room(
                me_id=a, title="T", member_ids=[b],
            )


# ──────────────────────────────────────────────────────────────────
# invite_members
# ──────────────────────────────────────────────────────────────────

class TestInviteMembersFlow:
    async def test_send_and_invite_share_room_first_lock_order(
        self, seed_users, seed_friendship, session_factory, chat_fanout_stub,
        chat_fcm_stub, message_service, patch_external_clients, monkeypatch,
    ):
        a, b, c = await seed_users(3)
        await seed_friendship(a, b)
        await seed_friendship(a, c)
        room_service = RoomService(
            uow=UnitOfWork(session_factory),
            fanout_service=chat_fanout_stub,
            message_service=message_service,
        )
        room = await room_service.create_group_room(
            me_id=a, title="lock-order", member_ids=[b],
        )

        insert_started = asyncio.Event()
        allow_insert = asyncio.Event()
        invite_passed_room_lock = asyncio.Event()
        original_insert = ChatMessageRepository.insert
        original_count = ChatRoomMemberRepository.count_active_members

        async def stalled_insert(repo, document):
            if document["content"] == "hold-room-lock":
                insert_started.set()
                await allow_insert.wait()
            await original_insert(repo, document)

        async def observed_count(repo, room_id):
            invite_passed_room_lock.set()
            return await original_count(repo, room_id)

        monkeypatch.setattr(ChatMessageRepository, "insert", stalled_insert)
        monkeypatch.setattr(
            ChatRoomMemberRepository, "count_active_members", observed_count,
        )

        sender = MessageService(
            uow=UnitOfWork(session_factory),
            fanout_service=chat_fanout_stub,
            fcm_service_factory=lambda: chat_fcm_stub,
        )
        send_task = asyncio.create_task(sender.send_message(
            sender_user_id=b,
            sender_session_id="WS_B",
            room_id=room.chat_room_id,
            client_msg_id="cmid-lock-order",
            msg_type=MessageType.TEXT,
            content="hold-room-lock",
        ))
        await insert_started.wait()

        inviter = RoomService(
            uow=UnitOfWork(session_factory),
            fanout_service=chat_fanout_stub,
            message_service=message_service,
        )
        invite_task = asyncio.create_task(inviter.invite_members(
            me_id=a, room_id=room.chat_room_id, user_ids=[c],
        ))
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(invite_passed_room_lock.wait(), timeout=0.1)
        finally:
            allow_insert.set()

        send_ack, invite_result = await asyncio.wait_for(
            asyncio.gather(send_task, invite_task), timeout=2,
        )
        assert send_ack.server_seq > 0
        assert invite_result == ([c], [])

    async def test_concurrent_invites_cannot_exceed_100_active_members(
        self, seed_users, session_factory, patch_external_clients, monkeypatch,
    ):
        users = await seed_users(101)
        creator, *rest = users
        initial_members = [creator, *rest[:98]]
        candidates = rest[98:]

        async with session_factory() as session:
            room = ChatRoom(type=ChatRoomType.GROUP, title="limit", creator_id=creator)
            session.add(room)
            await session.flush()
            room_id = str(room.chat_room_id)
            session.add_all([
                ChatRoomMember(chat_room_id=room_id, user_id=user_id)
                for user_id in initial_members
            ])
            session.add_all([
                Friendship(
                    requester_id=creator,
                    addressee_id=user_id,
                    status=FriendshipStatus.ACCEPTED,
                )
                for user_id in candidates
            ])
            await session.commit()

        original_count = ChatRoomMemberRepository.count_active_members
        second_counted = asyncio.Event()
        count_calls = 0

        async def coordinated_current_seq(_message_repo, _room_id):
            return 0

        async def coordinated_count(repo, target_room_id):
            nonlocal count_calls
            count = await original_count(repo, target_room_id)
            count_calls += 1
            if count_calls == 1:
                try:
                    await asyncio.wait_for(second_counted.wait(), timeout=1)
                except TimeoutError:
                    pass
            else:
                second_counted.set()
            return count

        monkeypatch.setattr(
            RoomService,
            "_get_allocated_current_seq",
            staticmethod(coordinated_current_seq),
        )
        monkeypatch.setattr(
            ChatRoomMemberRepository,
            "count_active_members",
            coordinated_count,
        )

        async def invite(user_id):
            service = RoomService(
                uow=UnitOfWork(session_factory),
                fanout_service=None,
                message_service=None,
            )
            return await service._invite_members_tx(
                me_id=creator,
                room_id=room_id,
                user_ids=[user_id],
            )

        results = await asyncio.gather(
            *(invite(user_id) for user_id in candidates),
            return_exceptions=True,
        )

        assert sum(not isinstance(result, BaseException) for result in results) == 1
        assert sum(
            isinstance(result, ValueError) and "최대 100명" in str(result)
            for result in results
        ) == 1
        async with session_factory() as session:
            active_count = await session.scalar(
                select(func.count()).select_from(ChatRoomMember).where(
                    ChatRoomMember.chat_room_id == room_id,
                    ChatRoomMember.is_left.is_(False),
                )
            )
        assert active_count == 100

    async def test_invite_new_member_and_rejoin_preserves_last_read(
        self, uow, seed_users, seed_friendship, chat_fanout_stub,
        session_factory, redis_hot, patch_external_clients, message_service,
    ):
        a, b, c = await seed_users(3)
        await seed_friendship(a, b)
        await seed_friendship(a, c)

        service = RoomService(uow=uow, fanout_service=chat_fanout_stub, message_service=message_service)
        # 1) a + b 2명 방 생성
        room_dto = await service.create_group_room(
            me_id=a, title="T", member_ids=[b],
        )
        room_id = room_dto.chat_room_id
        chat_fanout_stub.reset_mock()

        # 2) b 의 last_read 를 15 로 세팅 후 퇴장 시뮬레이션
        async with session_factory() as s:
            b_member = await s.get(ChatRoomMember, (room_id, b))
            b_member.last_read_message_server_seq = 15
            b_member.is_left = True
            await s.commit()

        # current_seq 가 30 인 상태로 세팅
        await redis_hot.set(room_seq_key(room_id), "30")

        # 3) c (신규) + b (재초대) 두 명 동시 초대
        invited, skipped = await service.invite_members(
            me_id=a, room_id=room_id, user_ids=[b, c],
        )

        assert sorted(invited) == sorted([b, c])
        assert skipped == []

        async with session_factory() as s:
            members = (await s.execute(
                select(ChatRoomMember).where(ChatRoomMember.chat_room_id == room_id)
            )).scalars().all()
            by_id = {m.user_id: m for m in members}
            # b: 재초대 — is_left 가 false 로 전환, last_read 는 유지
            assert by_id[b].is_left is False
            assert by_id[b].last_read_message_server_seq == 15
            # c: 신규 — last_read = current_seq (30)
            assert by_id[c].is_left is False
            assert by_id[c].last_read_message_server_seq == 30

        # Redis — 부분 SADD 대신 캐시를 무효화하고, 신규/재초대 unread 만 시드한다.
        cached = await redis_hot.smembers(room_members_key(room_id))
        assert cached == set()
        # 재초대 b: seq gap 안에 실제 사용자 메시지가 없으므로 유령 unread를 만들지 않는다.
        assert await redis_hot.hget(unread_key(b), room_id) == "0"
        # 신규 c: unread = 0
        assert await redis_hot.hget(unread_key(c), room_id) == "0"

        # fan_out_to_user 대상자에게만 room_joined (초대자 자신 제외)
        invited_targets = {call.args[0] for call in chat_fanout_stub.fan_out_to_user.call_args_list}
        assert invited_targets == {b, c}

    async def test_already_active_member_is_skipped(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, patch_external_clients, message_service,
    ):
        a, b, _ = await seed_users(3)
        await seed_friendship(a, b)

        service = RoomService(uow=uow, fanout_service=chat_fanout_stub, message_service=message_service)
        room_dto = await service.create_group_room(
            me_id=a, title="T", member_ids=[b],
        )

        # b 를 다시 초대 → 이미 멤버라 skip
        invited, skipped = await service.invite_members(
            me_id=a, room_id=room_dto.chat_room_id, user_ids=[b],
        )
        assert invited == []
        assert skipped == [b]

    async def test_inviter_must_be_active_member(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, patch_external_clients, message_service,
    ):
        a, b, c = await seed_users(3)
        await seed_friendship(a, b)

        service = RoomService(uow=uow, fanout_service=chat_fanout_stub, message_service=message_service)
        room = await service.create_group_room(
            me_id=a, title="T", member_ids=[b],
        )

        # c 는 방 멤버 아님
        with pytest.raises(PermissionError):
            await service.invite_members(
                me_id=c, room_id=room.chat_room_id, user_ids=[b],
            )

    async def test_direct_room_rejects_invite(
        self, uow, seed_users, chat_fanout_stub, patch_external_clients, message_service,
    ):
        a, b, _ = await seed_users(3)
        service = RoomService(uow=uow, fanout_service=chat_fanout_stub, message_service=message_service)
        direct = await service.create_direct_room(me_id=a, peer_user_id=b)

        with pytest.raises(ValueError, match="그룹 방에만"):
            await service.invite_members(
                me_id=a, room_id=direct.chat_room_id, user_ids=[b],
            )


# ──────────────────────────────────────────────────────────────────
# leave_room
# ──────────────────────────────────────────────────────────────────

class TestLeaveRoomFlow:
    async def test_leave_removes_from_redis_and_marks_is_left(
        self, uow, seed_users, seed_friendship, chat_fanout_stub,
        session_factory, redis_hot, patch_external_clients, message_service,
    ):
        a, b, _ = await seed_users(3)
        await seed_friendship(a, b)

        service = RoomService(uow=uow, fanout_service=chat_fanout_stub, message_service=message_service)
        room = await service.create_group_room(
            me_id=a, title="T", member_ids=[b],
        )
        chat_fanout_stub.reset_mock()

        await service.leave_room(me_id=b, room_id=room.chat_room_id)

        # Redis SREM + HDEL
        cached = await redis_hot.smembers(room_members_key(room.chat_room_id))
        assert cached == {a}
        assert await redis_hot.hget(unread_key(b), room.chat_room_id) is None

        # RDB — b 의 row 는 is_left=true
        async with session_factory() as s:
            b_row = await s.get(ChatRoomMember, (room.chat_room_id, b))
            assert b_row.is_left is True

        # fan_out — 본인에게 room_left
        chat_fanout_stub.fan_out_to_user.assert_awaited_once()
        call = chat_fanout_stub.fan_out_to_user.call_args
        assert call.args[0] == b
        assert call.args[1] == {"type": "room_left", "room_id": room.chat_room_id}

    async def test_left_member_cannot_send_with_stale_member_cache(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, redis_hot,
        patch_external_clients, message_service,
    ):
        a, b, _ = await seed_users(3)
        await seed_friendship(a, b)
        service = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await service.create_group_room(me_id=a, title="T", member_ids=[b])
        await service.leave_room(me_id=b, room_id=room.chat_room_id)
        await redis_hot.sadd(room_members_key(room.chat_room_id), b)

        with pytest.raises(PermissionError, match="멤버가 아닙니다"):
            await message_service.send_message(
                sender_user_id=b,
                sender_session_id="WS_B",
                room_id=room.chat_room_id,
                client_msg_id="cm-stale-member",
                msg_type=MessageType.TEXT,
                content="blocked",
            )

    async def test_direct_room_rejects_leave(
        self, uow, seed_users, chat_fanout_stub, patch_external_clients, message_service,
    ):
        a, b, _ = await seed_users(3)
        service = RoomService(uow=uow, fanout_service=chat_fanout_stub, message_service=message_service)
        direct = await service.create_direct_room(me_id=a, peer_user_id=b)

        with pytest.raises(ValueError, match="그룹 방만"):
            await service.leave_room(me_id=a, room_id=direct.chat_room_id)


# ──────────────────────────────────────────────────────────────────
# kick_member
# ──────────────────────────────────────────────────────────────────

class TestKickMemberFlow:
    async def test_creator_kicks_target(
        self, uow, seed_users, seed_friendship, chat_fanout_stub,
        session_factory, redis_hot, patch_external_clients, message_service,
    ):
        a, b, _ = await seed_users(3)
        await seed_friendship(a, b)

        service = RoomService(uow=uow, fanout_service=chat_fanout_stub, message_service=message_service)
        room = await service.create_group_room(
            me_id=a, title="T", member_ids=[b],
        )
        chat_fanout_stub.reset_mock()

        await service.kick_member(
            me_id=a, room_id=room.chat_room_id, target_user_id=b,
        )

        cached = await redis_hot.smembers(room_members_key(room.chat_room_id))
        assert cached == {a}

        async with session_factory() as s:
            b_row = await s.get(ChatRoomMember, (room.chat_room_id, b))
            assert b_row.is_left is True

        chat_fanout_stub.fan_out_to_user.assert_awaited_once()
        call = chat_fanout_stub.fan_out_to_user.call_args
        assert call.args[0] == b
        assert call.args[1]["type"] == "room_left"

    async def test_kicked_member_cannot_send_with_stale_member_cache(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, redis_hot,
        patch_external_clients, message_service,
    ):
        a, b, _ = await seed_users(3)
        await seed_friendship(a, b)
        service = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await service.create_group_room(me_id=a, title="T", member_ids=[b])
        await service.kick_member(
            me_id=a, room_id=room.chat_room_id, target_user_id=b,
        )
        await redis_hot.sadd(room_members_key(room.chat_room_id), b)

        with pytest.raises(PermissionError, match="멤버가 아닙니다"):
            await message_service.send_message(
                sender_user_id=b,
                sender_session_id="WS_B",
                room_id=room.chat_room_id,
                client_msg_id="cm-stale-kicked",
                msg_type=MessageType.TEXT,
                content="blocked",
            )

    async def test_non_creator_cannot_kick(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, patch_external_clients, message_service,
    ):
        a, b, c = await seed_users(3)
        await seed_friendship(a, b)
        await seed_friendship(a, c)

        service = RoomService(uow=uow, fanout_service=chat_fanout_stub, message_service=message_service)
        room = await service.create_group_room(
            me_id=a, title="T", member_ids=[b, c],
        )

        # b 는 creator 아님
        with pytest.raises(PermissionError, match="방장"):
            await service.kick_member(
                me_id=b, room_id=room.chat_room_id, target_user_id=c,
            )

    async def test_creator_after_leaving_loses_kick_permission(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, patch_external_clients, message_service,
    ):
        """PHASE_2 P5 — creator 가 leave 하면 권한 승계 없이 kick 불가."""
        a, b, c = await seed_users(3)
        await seed_friendship(a, b)
        await seed_friendship(a, c)

        service = RoomService(uow=uow, fanout_service=chat_fanout_stub, message_service=message_service)
        room = await service.create_group_room(
            me_id=a, title="T", member_ids=[b, c],
        )

        await service.leave_room(me_id=a, room_id=room.chat_room_id)

        with pytest.raises(PermissionError, match="이미 방을 떠난"):
            await service.kick_member(
                me_id=a, room_id=room.chat_room_id, target_user_id=b,
            )
