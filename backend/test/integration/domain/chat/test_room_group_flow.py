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
from app.domain.auth.model.user import User, UserStatus
from app.domain.auth.repository.user import UserRepository
from app.domain.chat.model.chat_message import MessageType
from app.domain.chat.model.chat_room import ChatRoom, ChatRoomType
from app.domain.chat.model.chat_room_member import ChatRoomMember
from app.domain.chat.repository.chat_member import ChatRoomMemberRepository
from app.domain.chat.repository.chat_message import ChatMessageRepository
from app.domain.chat.service.message import MessageService
from app.domain.chat.service.room import RoomService
from app.domain.friend.model.friendship import Friendship, FriendshipStatus


pytestmark = pytest.mark.integration


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


class TestCreateGroupRoomFlow:
    async def test_rejects_inactive_target_with_real_account_lock(
        self, uow, seed_users, seed_friendship, chat_fanout_stub,
        session_factory, patch_external_clients, message_service,
    ):
        a, b = await seed_users(2)
        await seed_friendship(a, b)
        async with session_factory() as session:
            target = await session.get(User, b)
            target.status = UserStatus.INACTIVE
            await session.commit()

        service = RoomService(
            uow=uow,
            fanout_service=chat_fanout_stub,
            message_service=message_service,
        )
        with pytest.raises(ValueError, match="비활성 계정"):
            await service.create_group_room(me_id=a, title="blocked", member_ids=[b])

        async with session_factory() as session:
            assert (await session.execute(select(ChatRoom))).scalars().all() == []

    async def test_target_deactivation_waits_for_room_membership_commit(
        self, seed_users, seed_friendship, chat_fanout_stub, session_factory,
        patch_external_clients, message_service, monkeypatch,
    ):
        a, b = await seed_users(2)
        await seed_friendship(a, b)
        locked = asyncio.Event()
        release = asyncio.Event()
        original = UserRepository.lock_active_user_ids

        async def pause_after_account_locks(repo, user_ids):
            active = await original(repo, user_ids)
            locked.set()
            await release.wait()
            return active

        monkeypatch.setattr(
            UserRepository, "lock_active_user_ids", pause_after_account_locks,
        )
        service = RoomService(
            uow=UnitOfWork(session_factory), fanout_service=chat_fanout_stub,
            message_service=message_service,
        )
        create_task = asyncio.create_task(service.create_group_room(
            me_id=a, title="account-lock", member_ids=[b],
        ))
        await asyncio.wait_for(locked.wait(), timeout=5)

        async def deactivate_target():
            async with session_factory() as session:
                target = await session.get(User, b, with_for_update=True)
                target.status = UserStatus.INACTIVE
                await session.commit()

        deactivate_task = asyncio.create_task(deactivate_target())
        await asyncio.sleep(0.1)
        assert not deactivate_task.done()

        release.set()
        room = await asyncio.wait_for(create_task, timeout=5)
        await asyncio.wait_for(deactivate_task, timeout=5)
        async with session_factory() as session:
            member = await session.get(ChatRoomMember, (room.chat_room_id, b))
            assert member.is_left is False
            assert (await session.get(User, b)).status == UserStatus.INACTIVE

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

        cached = await redis_hot.smembers(room_members_key(dto.chat_room_id))
        assert cached == {a, b, c}
        for uid in (a, b, c):
            raw = await redis_hot.hget(unread_key(uid), dto.chat_room_id)
            assert raw == "0"

        assert chat_fanout_stub.fan_out_member_joined.await_count == 3
        calls = chat_fanout_stub.fan_out_member_joined.call_args_list
        assert {call.args[0] for call in calls} == {a, b, c}
        assert {call.args[1] for call in calls} == {dto.chat_room_id}

    async def test_delayed_initial_join_does_not_resurrect_member_after_leave(
        self, seed_users, seed_friendship, chat_fanout_stub, session_factory,
        redis_hot, patch_external_clients, message_service, monkeypatch,
    ):
        a, b = await seed_users(2)
        await seed_friendship(a, b)
        create_service = RoomService(
            uow=UnitOfWork(session_factory),
            fanout_service=chat_fanout_stub,
            message_service=message_service,
        )
        entered = asyncio.Event()
        resume = asyncio.Event()
        original_emit = create_service._emit_room_joined

        async def delayed_emit(*args, **kwargs):
            entered.set()
            await resume.wait()
            await original_emit(*args, **kwargs)

        monkeypatch.setattr(create_service, "_emit_room_joined", delayed_emit)
        create_task = asyncio.create_task(
            create_service.create_group_room(me_id=a, title="race", member_ids=[b])
        )
        await asyncio.wait_for(entered.wait(), timeout=5)

        async with session_factory() as session:
            room_id = str((await session.execute(select(ChatRoom.chat_room_id))).scalar_one())
        leave_service = RoomService(
            uow=UnitOfWork(session_factory),
            fanout_service=chat_fanout_stub,
            message_service=message_service,
        )
        await leave_service.leave_room(me_id=b, room_id=room_id)
        resume.set()
        await asyncio.wait_for(create_task, timeout=5)

        assert b not in await redis_hot.smembers(room_members_key(room_id))
        assert await redis_hot.hget(unread_key(b), room_id) is None
        joined_targets = {
            call.args[0] for call in chat_fanout_stub.fan_out_member_joined.call_args_list
        }
        assert b not in joined_targets

    async def test_inflight_join_control_delivery_does_not_block_leave(
        self, seed_users, seed_friendship, chat_fanout_stub, session_factory,
        patch_external_clients, message_service,
    ):
        """소켓 delivery는 room lock 커밋 이후라 느린 클라이언트가 방 mutation을 막지 않는다.

        stale room_joined 억제는 fanout checked delivery가 전달 직전 membership
        재확인으로 담당한다 (unit: test_delayed_member_joined_is_dropped_after_revocation).
        """
        a, b = await seed_users(2)
        await seed_friendship(a, b)
        delivery_started = asyncio.Event()
        release_delivery = asyncio.Event()

        async def block_target_delivery(user_id: str, _room_id: str):
            if user_id == b:
                delivery_started.set()
                await release_delivery.wait()

        chat_fanout_stub.fan_out_member_joined.side_effect = block_target_delivery
        create_service = RoomService(
            uow=UnitOfWork(session_factory),
            fanout_service=chat_fanout_stub,
            message_service=message_service,
        )
        create_task = asyncio.create_task(create_service.create_group_room(
            me_id=a, title="locked-control", member_ids=[b],
        ))
        await asyncio.wait_for(delivery_started.wait(), timeout=5)
        async with session_factory() as session:
            room_id = str((await session.execute(
                select(ChatRoom.chat_room_id)
            )).scalar_one())

        leave_service = RoomService(
            uow=UnitOfWork(session_factory),
            fanout_service=chat_fanout_stub,
            message_service=message_service,
        )
        await asyncio.wait_for(
            leave_service.leave_room(me_id=b, room_id=room_id), timeout=5,
        )

        release_delivery.set()
        await asyncio.wait_for(create_task, timeout=5)

        async with session_factory() as session:
            member = await session.get(ChatRoomMember, (room_id, b))
            assert member.is_left is True

    async def test_non_friend_target_raises(
        self, uow, seed_users, chat_fanout_stub, patch_external_clients, message_service,
    ):
        a, b, _ = await seed_users(3)
        service = RoomService(uow=uow, fanout_service=chat_fanout_stub, message_service=message_service)
        with pytest.raises(ValueError, match="친구가 아닌"):
            await service.create_group_room(
                me_id=a, title="T", member_ids=[b],
            )


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
        captured_push: dict = {}

        def capture_push(**kwargs):
            captured_push.update(kwargs)

        monkeypatch.setattr(sender, "_spawn_push_task", capture_push)
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
        assert sorted(captured_push["recipient_generations"]) == [a]

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
        room_dto = await service.create_group_room(
            me_id=a, title="T", member_ids=[b],
        )
        room_id = room_dto.chat_room_id
        chat_fanout_stub.reset_mock()
        delivery_order: list[tuple[str, str]] = []

        async def record_subscribe(user_id, _room_id, *, authorization_locked=False):
            assert authorization_locked is True
            delivery_order.append(("subscribe", user_id))

        async def record_joined(user_id, _room_id):
            delivery_order.append(("joined", user_id))

        chat_fanout_stub.subscribe_user_to_room.side_effect = record_subscribe
        chat_fanout_stub.fan_out_member_joined.side_effect = record_joined

        async with session_factory() as s:
            b_member = await s.get(ChatRoomMember, (room_id, b))
            b_member.last_read_message_server_seq = 15
            b_member.is_left = True
            await s.commit()

        await redis_hot.set(room_seq_key(room_id), "30")

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
            assert by_id[b].is_left is False
            assert by_id[b].last_read_message_server_seq == 15
            assert by_id[c].is_left is False
            assert by_id[c].last_read_message_server_seq == 30

        # Redis — 부분 SADD 대신 캐시를 무효화하고, 신규/재초대 unread 만 시드한다.
        cached = await redis_hot.smembers(room_members_key(room_id))
        assert cached == set()
        assert await redis_hot.hget(unread_key(b), room_id) == "0"
        assert await redis_hot.hget(unread_key(c), room_id) == "0"

        invited_targets = {
            call.args[0]
            for call in chat_fanout_stub.fan_out_member_joined.call_args_list
        }
        assert invited_targets == {b, c}
        for user_id in (b, c):
            assert delivery_order.index(("subscribe", user_id)) < delivery_order.index(
                ("joined", user_id)
            )

    async def test_already_active_member_is_skipped(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, patch_external_clients, message_service,
    ):
        a, b, _ = await seed_users(3)
        await seed_friendship(a, b)

        service = RoomService(uow=uow, fanout_service=chat_fanout_stub, message_service=message_service)
        room_dto = await service.create_group_room(
            me_id=a, title="T", member_ids=[b],
        )

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

        cached = await redis_hot.smembers(room_members_key(room.chat_room_id))
        assert cached == {a}
        assert await redis_hot.hget(unread_key(b), room.chat_room_id) is None

        async with session_factory() as s:
            b_row = await s.get(ChatRoomMember, (room.chat_room_id, b))
            assert b_row.is_left is True

        chat_fanout_stub.fan_out_member_removed.assert_awaited_once_with(
            b, room.chat_room_id,
        )

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

        chat_fanout_stub.fan_out_member_removed.assert_awaited_once_with(
            b, room.chat_room_id,
        )

    async def test_concurrent_kick_then_leave_observes_removed_state(
        self, seed_users, seed_friendship, chat_fanout_stub, session_factory,
        patch_external_clients, message_service, monkeypatch,
    ):
        a, b = await seed_users(2)
        await seed_friendship(a, b)
        creator_service = RoomService(
            uow=UnitOfWork(session_factory), fanout_service=chat_fanout_stub,
            message_service=message_service,
        )
        room = await creator_service.create_group_room(
            me_id=a, title="serialized-removal", member_ids=[b],
        )
        locked = asyncio.Event()
        release = asyncio.Event()
        original = ChatRoomMemberRepository.find_for_update

        async def pause_first_target_lock(repo, room_id, user_id):
            member = await original(repo, room_id, user_id)
            if user_id == b and not locked.is_set():
                locked.set()
                await release.wait()
            return member

        monkeypatch.setattr(
            ChatRoomMemberRepository, "find_for_update", pause_first_target_lock,
        )
        kick_service = RoomService(
            uow=UnitOfWork(session_factory), fanout_service=chat_fanout_stub,
            message_service=message_service,
        )
        leave_service = RoomService(
            uow=UnitOfWork(session_factory), fanout_service=chat_fanout_stub,
            message_service=message_service,
        )
        kick_task = asyncio.create_task(kick_service.kick_member(
            me_id=a, room_id=room.chat_room_id, target_user_id=b,
        ))
        await asyncio.wait_for(locked.wait(), timeout=5)
        leave_task = asyncio.create_task(leave_service.leave_room(
            me_id=b, room_id=room.chat_room_id,
        ))
        await asyncio.sleep(0.1)
        assert not leave_task.done()

        release.set()
        await asyncio.wait_for(kick_task, timeout=5)
        with pytest.raises(PermissionError, match="활성 멤버"):
            await asyncio.wait_for(leave_task, timeout=5)

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
