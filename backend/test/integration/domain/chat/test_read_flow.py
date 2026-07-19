"""RoomService.mark_read 통합 테스트 (PHASE_2 #3).

RDB 의 `GREATEST(COALESCE(last_read, 0), :new_seq)` 규약이 실제 Postgres 에서
작동하는지 + Redis unread 리셋 + fan-out 이벤트 구조 end-to-end 검증.
"""
import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio

from app.core.chat.redis_key import room_seq_key, unread_key
from app.database.session import UnitOfWork
from app.domain.chat.model.chat_message import MessageType
from app.domain.chat.model.chat_room_member import ChatRoomMember
from app.domain.chat.repository.chat_message import ChatMessageRepository
from app.domain.chat.service import message as message_module
from app.domain.chat.service.exception import ChatRoomNotFoundError
from app.domain.chat.service.message import MessageService
from app.domain.chat.service.room import RoomService
from app.domain.chat.worker import reconcile as reconcile_module
from app.domain.friend.model.friendship import Friendship, FriendshipStatus


pytestmark = pytest.mark.integration


async def _insert_message(mongo_db, room_id: str, server_seq: int) -> None:
    await mongo_db.chat_message.insert_one({
        "_id": f"MSG_IT_{server_seq}",
        "chat_room_id": room_id,
        "server_seq": server_seq,
        "sender_id": "USER_IT_000",
        "type": "text",
        "content": f"message-{server_seq}",
        "created_at": datetime.now(timezone.utc),
        "edited_at": None,
        "deleted_at": None,
    })


async def test_unread_count_excludes_system_and_recovering_users_own_messages(mongo_db):
    room_id = "CR_IT_UNREAD_SEMANTICS"
    await mongo_db.chat_message.insert_many([
        {
            "_id": "MSG_IT_UNREAD_1",
            "chat_room_id": room_id,
            "server_seq": 1,
            "sender_id": "USER_IT_SELF",
            "type": "text",
        },
        {
            "_id": "MSG_IT_UNREAD_2",
            "chat_room_id": room_id,
            "server_seq": 2,
            "sender_id": "USER_IT_OTHER",
            "type": "text",
        },
        {
            "_id": "MSG_IT_UNREAD_3",
            "chat_room_id": room_id,
            "server_seq": 3,
            "sender_id": "USER_IT_OTHER",
            "type": "system",
        },
    ])

    count = await ChatMessageRepository(mongo_db).count_after_seq(
        chat_room_id=room_id,
        after_seq=0,
        exclude_sender_user_id="USER_IT_SELF",
    )

    assert count == 1


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


class TestMarkReadFlow:
    async def test_unread_recoveries_for_same_user_are_serialized(
        self, session_factory,
    ):
        first_entered = asyncio.Event()
        release_first = asyncio.Event()
        second_entered = asyncio.Event()
        calls = 0

        async def locked_recovery(user_id, only_room=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                first_entered.set()
                await release_first.wait()
            else:
                second_entered.set()
            return ({}, {}, {}), "ok"

        with (
            patch.object(reconcile_module, "_session_factory", session_factory),
            patch.object(
                reconcile_module,
                "_recover_unread_for_user_locked",
                side_effect=locked_recovery,
            ),
        ):
            first = asyncio.create_task(
                reconcile_module.recover_unread_for_user("USER_IT_RECOVERY_LOCK"),
            )
            await first_entered.wait()
            second = asyncio.create_task(
                reconcile_module.recover_unread_for_user("USER_IT_RECOVERY_LOCK"),
            )

            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(second_entered.wait(), timeout=0.5)
            release_first.set()
            await asyncio.wait_for(asyncio.gather(first, second), timeout=5)

        assert second_entered.is_set()

    async def test_mark_read_and_get_unread(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, message_service,
        session_factory, redis_hot, mongo_db, patch_external_clients,
    ):
        a, b, _ = await seed_users(3)
        await seed_friendship(a, b)

        service = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await service.create_group_room(me_id=a, title="T", member_ids=[b])
        await _insert_message(mongo_db, room.chat_room_id, 10)

        await redis_hot.set(room_seq_key(room.chat_room_id), 10)
        await redis_hot.hset(unread_key(b), room.chat_room_id, 5)

        chat_fanout_stub.reset_mock()
        final = await service.mark_read(
            me_id=b, me_session_id="WS_B", room_id=room.chat_room_id,
            up_to_server_seq=10,
        )
        assert final == 10

        async with session_factory() as s:
            b_row = await s.get(ChatRoomMember, (room.chat_room_id, b))
            assert b_row.last_read_message_server_seq == 10
            assert b_row.last_read_at is not None

        raw = await redis_hot.hget(unread_key(b), room.chat_room_id)
        assert raw == "0"

        chat_fanout_stub.fan_out_to_session.assert_not_awaited()

        chat_fanout_stub.fan_out_to_room.assert_awaited_once()
        room_call = chat_fanout_stub.fan_out_to_room.call_args
        assert room_call.args[0] == room.chat_room_id
        assert room_call.args[1] == {
            "type": "read",
            "user_id": b,
            "sender_session_id": "WS_B",
            "up_to_server_seq": 10,
        }

    async def test_reserved_seq_is_not_read_before_mongo_insert(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, message_service,
        session_factory, redis_hot, mongo_db, patch_external_clients,
    ):
        a, b, _ = await seed_users(3)
        await seed_friendship(a, b)
        service = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await service.create_group_room(me_id=a, title="T", member_ids=[b])
        await _insert_message(mongo_db, room.chat_room_id, 12)
        await redis_hot.set(room_seq_key(room.chat_room_id), 12)

        reserved = await MessageService._allocate_seq(
            ChatMessageRepository(mongo_db), redis_hot,
            room_id=room.chat_room_id,
        )
        assert reserved == 13

        final = await service.mark_read(
            me_id=b, me_session_id="WS_B", room_id=room.chat_room_id,
            up_to_server_seq=10**15,
        )
        assert final == 12

        await _insert_message(mongo_db, room.chat_room_id, reserved)
        async with session_factory() as session:
            member = await session.get(ChatRoomMember, (room.chat_room_id, b))
            assert member.last_read_message_server_seq == 12

    async def test_concurrent_send_is_not_counted_in_residual_and_redis_delta(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, chat_fcm_stub,
        message_service, session_factory, redis_hot, mongo_db, patch_external_clients,
    ):
        a, b, _ = await seed_users(3)
        await seed_friendship(a, b)
        room_service = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await room_service.create_group_room(
            me_id=a, title="T", member_ids=[b],
        )
        await _insert_message(mongo_db, room.chat_room_id, 10)
        await redis_hot.set(room_seq_key(room.chat_room_id), 10)
        await redis_hot.hset(unread_key(b), room.chat_room_id, 1)

        count_started = asyncio.Event()
        release_count = asyncio.Event()
        original_count = ChatMessageRepository.count_after_seq

        async def paused_count(repo, *args, **kwargs):
            count_started.set()
            await release_count.wait()
            return await original_count(repo, *args, **kwargs)

        sender = MessageService(
            uow=UnitOfWork(session=session_factory),
            fanout_service=chat_fanout_stub,
            fcm_service_factory=lambda: chat_fcm_stub,
        )
        send_progress = asyncio.Event()
        mongo_inserted = asyncio.Event()
        unread_bumped = asyncio.Event()
        original_insert = message_module._insert_with_definitive_outcome
        original_bump = sender._bump_unread

        async def observed_insert(*args, **kwargs):
            send_progress.set()
            result = await original_insert(*args, **kwargs)
            mongo_inserted.set()
            return result

        async def observed_bump(*args, **kwargs):
            send_progress.set()
            result = await original_bump(*args, **kwargs)
            unread_bumped.set()
            return result

        with (
            patch.object(ChatMessageRepository, "count_after_seq", paused_count),
            patch.object(message_module, "_insert_with_definitive_outcome", observed_insert),
            patch.object(sender, "_bump_unread", observed_bump),
        ):
            read_task = asyncio.create_task(room_service.mark_read(
                me_id=b,
                me_session_id="WS_B",
                room_id=room.chat_room_id,
                up_to_server_seq=10,
            ))
            await asyncio.wait_for(count_started.wait(), timeout=1)
            send_task = asyncio.create_task(sender.send_message(
                sender_user_id=a,
                sender_session_id="WS_A",
                room_id=room.chat_room_id,
                client_msg_id="cm-unread-residual-delta",
                msg_type=MessageType.TEXT,
                content="concurrent",
            ))
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(send_progress.wait(), timeout=1)
            release_count.set()
            await asyncio.gather(read_task, send_task)

        assert mongo_inserted.is_set()
        assert unread_bumped.is_set()
        assert int(await redis_hot.hget(unread_key(b), room.chat_room_id)) == 1

    async def test_unread_recovery_does_not_double_count_concurrent_send(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, chat_fcm_stub,
        message_service, session_factory, redis_hot, mongo_db, patch_external_clients,
    ):
        a, b, _ = await seed_users(3)
        await seed_friendship(a, b)
        room_service = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await room_service.create_group_room(
            me_id=a, title="T", member_ids=[b],
        )
        await _insert_message(mongo_db, room.chat_room_id, 10)
        await redis_hot.set(room_seq_key(room.chat_room_id), 10)
        await room_service.mark_read(
            me_id=b,
            me_session_id="WS_B",
            room_id=room.chat_room_id,
            up_to_server_seq=10,
        )
        await redis_hot.hset(unread_key(b), room.chat_room_id, 0)

        count_started = asyncio.Event()
        release_count = asyncio.Event()
        original_count = ChatMessageRepository.count_after_seq

        async def paused_count(repo, *args, **kwargs):
            count_started.set()
            await release_count.wait()
            return await original_count(repo, *args, **kwargs)

        sender = MessageService(
            uow=UnitOfWork(session=session_factory),
            fanout_service=chat_fanout_stub,
            fcm_service_factory=lambda: chat_fcm_stub,
        )
        send_progress = asyncio.Event()
        mongo_inserted = asyncio.Event()
        unread_bumped = asyncio.Event()
        original_insert = message_module._insert_with_definitive_outcome
        original_bump = sender._bump_unread

        async def observed_insert(*args, **kwargs):
            send_progress.set()
            result = await original_insert(*args, **kwargs)
            mongo_inserted.set()
            return result

        async def observed_bump(*args, **kwargs):
            send_progress.set()
            result = await original_bump(*args, **kwargs)
            unread_bumped.set()
            return result

        with (
            patch.object(reconcile_module, "_session_factory", session_factory),
            patch.object(ChatMessageRepository, "count_after_seq", paused_count),
            patch.object(message_module, "_insert_with_definitive_outcome", observed_insert),
            patch.object(sender, "_bump_unread", observed_bump),
        ):
            recover_task = asyncio.create_task(
                reconcile_module.recover_unread_for_user(
                    b, only_room=room.chat_room_id,
                ),
            )
            await asyncio.wait_for(count_started.wait(), timeout=1)
            send_task = asyncio.create_task(sender.send_message(
                sender_user_id=a,
                sender_session_id="WS_A",
                room_id=room.chat_room_id,
                client_msg_id="cm-unread-recovery-race",
                msg_type=MessageType.TEXT,
                content="concurrent recovery",
            ))
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(send_progress.wait(), timeout=1)
            release_count.set()
            counts, _ = await asyncio.gather(recover_task, send_task)

        assert mongo_inserted.is_set()
        assert unread_bumped.is_set()
        assert counts[room.chat_room_id] == 0
        assert int(await redis_hot.hget(unread_key(b), room.chat_room_id)) == 1

    async def test_greatest_prevents_regress(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, message_service,
        session_factory, redis_hot, mongo_db, patch_external_clients,
    ):
        """이미 높은 seq 가 기록된 뒤 과거 seq 로 호출 → 기존 값 유지, 반환도 기존 값."""
        a, b, _ = await seed_users(3)
        await seed_friendship(a, b)

        service = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await service.create_group_room(me_id=a, title="T", member_ids=[b])
        await _insert_message(mongo_db, room.chat_room_id, 20)

        await redis_hot.set(room_seq_key(room.chat_room_id), 20)
        first = await service.mark_read(
            me_id=b, me_session_id="WS_B", room_id=room.chat_room_id,
            up_to_server_seq=20,
        )
        assert first == 20

        second = await service.mark_read(
            me_id=b, me_session_id="WS_B", room_id=room.chat_room_id,
            up_to_server_seq=5,
        )
        assert second == 20

        async with session_factory() as s:
            b_row = await s.get(ChatRoomMember, (room.chat_room_id, b))
            assert b_row.last_read_message_server_seq == 20

    async def test_room_not_found_raises(
        self, uow, chat_fanout_stub, message_service, patch_external_clients,
    ):
        service = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        with pytest.raises(ChatRoomNotFoundError):
            await service.mark_read(
                me_id="U_ghost", me_session_id="WS_x", room_id="CR_none",
                up_to_server_seq=1,
            )

    async def test_left_member_cannot_mark_read(
        self, uow, seed_users, seed_friendship, chat_fanout_stub, message_service,
        session_factory, patch_external_clients,
    ):
        a, b, _ = await seed_users(3)
        await seed_friendship(a, b)

        service = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await service.create_group_room(me_id=a, title="T", member_ids=[b])
        await service.leave_room(me_id=b, room_id=room.chat_room_id)

        with pytest.raises(PermissionError):
            await service.mark_read(
                me_id=b, me_session_id="WS_B", room_id=room.chat_room_id,
                up_to_server_seq=5,
            )
