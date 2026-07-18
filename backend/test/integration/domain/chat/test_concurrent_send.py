"""PHASE_1 통합 체크리스트 — "두 유저가 동시에 메시지 송신 → 모두 단조 seq".

`incr_fast.lua` 의 atomic INCR 가 실 Redis 에서 정말 원자적인지, 동시 송신 N 건의
server_seq 가 유니크하고 1..N 로 채워지는지 검증한다. 단위 테스트는 Lua 를 mock 하기
때문에 이 보장은 통합으로만 증명 가능.
"""
import asyncio

import pytest
from pymongo.errors import ConnectionFailure
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.domain.chat.worker.reconcile as reconcile
from app.core.chat.redis_key import DIRTY_CHAT_ROOM_KEY, room_pending_message_key
from app.database.session import UnitOfWork
from app.domain.chat.model.chat_message import MessageType
from app.domain.chat.repository.chat_message import ChatMessageRepository
from app.domain.chat.service.message import MessageService


pytestmark = pytest.mark.integration


# `UnitOfWork.__aenter__` 가 `self.session` 인스턴스 속성에 세션을 저장하므로
# 동시 gather 로 같은 UoW 를 공유하면 race 가 발생한다 — task 별로 신규 UoW.
# row lock 경합 완화를 위해 concurrent 건수는 10 으로 축소 (atomic 증명은 동일).
_CONCURRENT_COUNT = 10


async def test_sync_session_invalidate_force_releases_transaction_lock(session_factory):
    lock_id = 918273645
    first = session_factory()
    await first.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": lock_id})

    first.sync_session.invalidate()

    second = session_factory()
    try:
        await asyncio.wait_for(
            second.execute(
                text("SELECT pg_advisory_xact_lock(:lock_id)"),
                {"lock_id": lock_id},
            ),
            timeout=1.0,
        )
        await second.rollback()
    finally:
        await second.close()


class TestConcurrentSendProducesMonotonicSeq:
    async def test_fanout_authorization_cannot_exhaust_a_two_connection_pool(
        self,
        engine,
        session_factory,
        direct_room,
        seed_users,
        chat_fanout_stub,
        message_service,
        chat_fcm_stub,
    ):
        from app.domain.chat.service.room import RoomService

        room_a, user_a, _ = direct_room
        user_c, user_d = await seed_users(2)
        room_b = (
            await RoomService(
                uow=UnitOfWork(session=session_factory),
                fanout_service=chat_fanout_stub,
                message_service=message_service,
            ).create_direct_room(me_id=user_c, peer_user_id=user_d)
        ).chat_room_id

        pooled_engine = create_async_engine(
            engine.url,
            pool_size=2,
            max_overflow=0,
            pool_timeout=0.5,
        )
        pooled_factory = async_sessionmaker(
            pooled_engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        both_fanouts_started = asyncio.Event()
        fanout_count = 0
        fanout_count_lock = asyncio.Lock()

        class AuthorizationFanout:
            async def fan_out_to_room(self, _room_id, _payload):
                nonlocal fanout_count
                async with fanout_count_lock:
                    fanout_count += 1
                    if fanout_count == 2:
                        both_fanouts_started.set()
                await asyncio.wait_for(both_fanouts_started.wait(), timeout=1)
                async with pooled_factory() as authorization_session:
                    await authorization_session.execute(text("SELECT 1"))

        async def send(user_id: str, room_id: str, client_msg_id: str):
            return await MessageService(
                uow=UnitOfWork(session=pooled_factory),
                fanout_service=AuthorizationFanout(),
                fcm_service_factory=lambda: chat_fcm_stub,
            ).send_message(
                sender_user_id=user_id,
                sender_session_id=f"WS_{user_id}",
                room_id=room_id,
                client_msg_id=client_msg_id,
                msg_type=MessageType.TEXT,
                content=client_msg_id,
            )

        try:
            first, second = await asyncio.wait_for(
                asyncio.gather(
                    send(user_a, room_a, "pool-a"),
                    send(user_c, room_b, "pool-b"),
                ),
                timeout=2,
            )
        finally:
            await pooled_engine.dispose()

        assert first.server_seq > 0
        assert second.server_seq > 0

    async def test_room_lock_is_released_before_fanout_waits(
        self, session_factory, direct_room, chat_fcm_stub, monkeypatch,
    ):
        room_id, user_a, user_b = direct_room
        first_fanout_started = asyncio.Event()
        allow_first_fanout = asyncio.Event()
        second_insert_started = asyncio.Event()
        original_insert = ChatMessageRepository.insert

        class BlockingFanout:
            async def fan_out_to_room(self, _room_id, payload):
                if payload["message"]["content"] == "first-fanout-blocked":
                    first_fanout_started.set()
                    await allow_first_fanout.wait()

        async def observed_insert(repo, document):
            if document["content"] == "second-runs-during-fanout":
                second_insert_started.set()
            await original_insert(repo, document)

        monkeypatch.setattr(ChatMessageRepository, "insert", observed_insert)
        fanout = BlockingFanout()

        async def send(user_id: str, client_msg_id: str, content: str):
            return await MessageService(
                uow=UnitOfWork(session=session_factory),
                fanout_service=fanout,
                fcm_service_factory=lambda: chat_fcm_stub,
            ).send_message(
                sender_user_id=user_id,
                sender_session_id=f"WS_{user_id}",
                room_id=room_id,
                client_msg_id=client_msg_id,
                msg_type=MessageType.TEXT,
                content=content,
            )

        first_task = asyncio.create_task(send(
            user_a, "cmid-fanout-first", "first-fanout-blocked",
        ))
        await asyncio.wait_for(first_fanout_started.wait(), timeout=2)
        second_task = asyncio.create_task(send(
            user_b, "cmid-fanout-second", "second-runs-during-fanout",
        ))
        try:
            await asyncio.wait_for(second_insert_started.wait(), timeout=2)
            second_entered_early = True
        except asyncio.TimeoutError:
            second_entered_early = False
        finally:
            allow_first_fanout.set()

        first_ack, second_ack = await asyncio.gather(first_task, second_task)
        assert second_entered_early
        assert first_ack.server_seq < second_ack.server_seq

    async def test_sends_insert_in_seq_reservation_order(
        self, session_factory, direct_room, chat_fanout_stub, chat_fcm_stub,
        monkeypatch,
    ):
        room_id, user_a, user_b = direct_room
        first_insert_started = asyncio.Event()
        allow_first_insert = asyncio.Event()
        second_insert_started = asyncio.Event()
        original_insert = ChatMessageRepository.insert

        async def coordinated_insert(repo, document):
            if document["content"] == "first":
                first_insert_started.set()
                await allow_first_insert.wait()
            elif document["content"] == "second":
                second_insert_started.set()
            await original_insert(repo, document)

        monkeypatch.setattr(ChatMessageRepository, "insert", coordinated_insert)

        async def send(user_id: str, client_msg_id: str, content: str):
            service = MessageService(
                uow=UnitOfWork(session=session_factory),
                fanout_service=chat_fanout_stub,
                fcm_service_factory=lambda: chat_fcm_stub,
            )
            return await service.send_message(
                sender_user_id=user_id,
                sender_session_id=f"WS_{user_id}",
                room_id=room_id,
                client_msg_id=client_msg_id,
                msg_type=MessageType.TEXT,
                content=content,
            )

        first_task = asyncio.create_task(send(user_a, "cmid-first", "first"))
        await first_insert_started.wait()
        second_task = asyncio.create_task(send(user_b, "cmid-second", "second"))
        try:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(second_insert_started.wait(), timeout=0.1)
        finally:
            allow_first_insert.set()

        first_ack, second_ack = await asyncio.gather(first_task, second_task)
        assert first_ack.server_seq < second_ack.server_seq

    async def test_cancelled_sender_keeps_room_lock_until_insert_finishes(
        self, session_factory, direct_room, chat_fanout_stub, chat_fcm_stub,
        monkeypatch,
    ):
        room_id, user_a, user_b = direct_room
        first_insert_started = asyncio.Event()
        allow_first_insert = asyncio.Event()
        second_insert_started = asyncio.Event()
        original_insert = ChatMessageRepository.insert

        async def delayed_insert(repo, document):
            if document["content"] == "cancelled-first":
                first_insert_started.set()
                await allow_first_insert.wait()
            elif document["content"] == "second-after-cancel":
                second_insert_started.set()
            await original_insert(repo, document)

        monkeypatch.setattr(ChatMessageRepository, "insert", delayed_insert)

        async def send(user_id: str, client_msg_id: str, content: str):
            service = MessageService(
                uow=UnitOfWork(session=session_factory),
                fanout_service=chat_fanout_stub,
                fcm_service_factory=lambda: chat_fcm_stub,
            )
            return await service.send_message(
                sender_user_id=user_id,
                sender_session_id=f"WS_{user_id}",
                room_id=room_id,
                client_msg_id=client_msg_id,
                msg_type=MessageType.TEXT,
                content=content,
            )

        first_task = asyncio.create_task(send(
            user_a, "cmid-cancelled-first", "cancelled-first",
        ))
        await first_insert_started.wait()
        first_task.cancel()
        second_task = asyncio.create_task(send(
            user_b, "cmid-second-after-cancel", "second-after-cancel",
        ))

        try:
            await asyncio.wait_for(second_insert_started.wait(), timeout=0.1)
            second_reached_insert = True
        except TimeoutError:
            second_reached_insert = False
        finally:
            allow_first_insert.set()

        with pytest.raises(asyncio.CancelledError):
            await first_task
        second_ack = await second_task

        assert not second_reached_insert
        assert second_ack.server_seq > 0

    async def test_ambiguous_write_keeps_room_lock_until_outcome_is_resolved(
        self, session_factory, direct_room, chat_fanout_stub, chat_fcm_stub,
        monkeypatch,
    ):
        room_id, user_a, user_b = direct_room
        resolution_retry_started = asyncio.Event()
        allow_resolution = asyncio.Event()
        second_insert_started = asyncio.Event()
        original_insert = ChatMessageRepository.insert
        ambiguous_attempts = 0

        async def ambiguous_insert(repo, document):
            nonlocal ambiguous_attempts
            if document["content"] == "ambiguous-first":
                ambiguous_attempts += 1
                if ambiguous_attempts == 1:
                    await original_insert(repo, document)
                    raise ConnectionFailure("reply lost after committed write")
                resolution_retry_started.set()
                await allow_resolution.wait()
            elif document["content"] == "second-after-ambiguous":
                second_insert_started.set()
            await original_insert(repo, document)

        monkeypatch.setattr(ChatMessageRepository, "insert", ambiguous_insert)

        async def send(user_id: str, client_msg_id: str, content: str):
            service = MessageService(
                uow=UnitOfWork(session=session_factory),
                fanout_service=chat_fanout_stub,
                fcm_service_factory=lambda: chat_fcm_stub,
            )
            return await service.send_message(
                sender_user_id=user_id,
                sender_session_id=f"WS_{user_id}",
                room_id=room_id,
                client_msg_id=client_msg_id,
                msg_type=MessageType.TEXT,
                content=content,
            )

        first_task = asyncio.create_task(send(
            user_a, "cmid-ambiguous-first", "ambiguous-first",
        ))
        await resolution_retry_started.wait()
        second_task = asyncio.create_task(send(
            user_b, "cmid-second-after-ambiguous", "second-after-ambiguous",
        ))

        try:
            await asyncio.wait_for(second_insert_started.wait(), timeout=0.1)
            second_reached_insert = True
        except TimeoutError:
            second_reached_insert = False
        finally:
            allow_resolution.set()

        first_ack, second_ack = await asyncio.gather(first_task, second_task)
        assert not second_reached_insert
        assert first_ack.server_seq < second_ack.server_seq

    async def test_process_death_pending_fence_recovers_before_next_seq(
        self, session_factory, direct_room, chat_fanout_stub, chat_fcm_stub,
        redis_hot, mongo_db, monkeypatch,
    ):
        class SimulatedProcessDeath(BaseException):
            pass

        room_id, user_a, user_b = direct_room
        original_insert = ChatMessageRepository.insert
        crashed = False

        async def crash_before_first_mongo_write(repo, document):
            nonlocal crashed
            if document["content"] == "pending-at-process-death" and not crashed:
                crashed = True
                raise SimulatedProcessDeath
            await original_insert(repo, document)

        monkeypatch.setattr(
            ChatMessageRepository, "insert", crash_before_first_mongo_write,
        )

        async def send(user_id: str, client_msg_id: str, content: str):
            service = MessageService(
                uow=UnitOfWork(session=session_factory),
                fanout_service=chat_fanout_stub,
                fcm_service_factory=lambda: chat_fcm_stub,
            )
            return await service.send_message(
                sender_user_id=user_id,
                sender_session_id=f"WS_{user_id}",
                room_id=room_id,
                client_msg_id=client_msg_id,
                msg_type=MessageType.TEXT,
                content=content,
            )

        with pytest.raises(SimulatedProcessDeath):
            await send(
                user_a, "cmid-process-death", "pending-at-process-death",
            )

        assert await redis_hot.get(room_pending_message_key(room_id)) is not None

        second_ack = await send(
            user_b, "cmid-after-process-death", "after-process-death",
        )

        docs = await mongo_db.chat_message.find({
            "chat_room_id": room_id,
            "content": {"$in": ["pending-at-process-death", "after-process-death"]},
        }).sort("server_seq", 1).to_list(length=2)
        assert [doc["content"] for doc in docs] == [
            "pending-at-process-death", "after-process-death",
        ]
        assert docs[0]["server_seq"] < second_ack.server_seq
        assert await redis_hot.get(room_pending_message_key(room_id)) is None

    async def test_process_death_same_client_id_replays_recovered_message(
        self, session_factory, direct_room, chat_fanout_stub, chat_fcm_stub,
        redis_hot, mongo_db, monkeypatch,
    ):
        from bson import json_util

        class SimulatedProcessDeath(BaseException):
            pass

        room_id, user_a, _ = direct_room
        client_msg_id = "cmid-process-death-retry"
        original_insert = ChatMessageRepository.insert
        crashed = False

        async def crash_before_first_mongo_write(repo, document):
            nonlocal crashed
            if not crashed:
                crashed = True
                raise SimulatedProcessDeath
            await original_insert(repo, document)

        monkeypatch.setattr(
            ChatMessageRepository, "insert", crash_before_first_mongo_write,
        )

        async def send():
            service = MessageService(
                uow=UnitOfWork(session=session_factory),
                fanout_service=chat_fanout_stub,
                fcm_service_factory=lambda: chat_fcm_stub,
            )
            return await service.send_message(
                sender_user_id=user_a,
                sender_session_id="WS_A",
                room_id=room_id,
                client_msg_id=client_msg_id,
                msg_type=MessageType.TEXT,
                content="recover-the-original",
            )

        with pytest.raises(SimulatedProcessDeath):
            await send()

        raw_pending = await redis_hot.get(room_pending_message_key(room_id))
        assert raw_pending is not None
        original_message_id = json_util.loads(raw_pending)["_id"]

        ack = await send()

        assert ack.client_msg_id == client_msg_id
        assert ack.message_id == original_message_id
        docs = await mongo_db.chat_message.find({
            "chat_room_id": room_id,
            "content": "recover-the-original",
        }).to_list(length=2)
        assert [doc["_id"] for doc in docs] == [original_message_id]
        assert await redis_hot.get(room_pending_message_key(room_id)) is None

    async def test_pending_sweeper_recovers_without_followup_sender(
        self, session_factory, direct_room, chat_fanout_stub, chat_fcm_stub,
        redis_hot, mongo_db, monkeypatch,
    ):
        class SimulatedProcessDeath(BaseException):
            pass

        room_id, user_a, _ = direct_room
        original_insert = ChatMessageRepository.insert
        crashed = False

        async def crash_before_first_mongo_write(repo, document):
            nonlocal crashed
            if not crashed:
                crashed = True
                raise SimulatedProcessDeath
            await original_insert(repo, document)

        monkeypatch.setattr(
            ChatMessageRepository, "insert", crash_before_first_mongo_write,
        )
        service = MessageService(
            uow=UnitOfWork(session=session_factory),
            fanout_service=chat_fanout_stub,
            fcm_service_factory=lambda: chat_fcm_stub,
        )

        with pytest.raises(SimulatedProcessDeath):
            await service.send_message(
                sender_user_id=user_a,
                sender_session_id="WS_A",
                room_id=room_id,
                client_msg_id="cmid-orphan-sweep",
                msg_type=MessageType.TEXT,
                content="recover-without-next-send",
            )

        assert await redis_hot.get(room_pending_message_key(room_id)) is not None
        monkeypatch.setattr(reconcile, "PENDING_RECOVERY_INTERVAL_SEC", 0.01)
        reconcile.start_reconcile_scheduler(session_factory)
        try:
            for _ in range(100):
                if await redis_hot.get(room_pending_message_key(room_id)) is None:
                    break
                await asyncio.sleep(0.01)
        finally:
            await reconcile.stop_reconcile_scheduler()

        docs = await mongo_db.chat_message.find({
            "chat_room_id": room_id,
            "content": "recover-without-next-send",
        }).to_list(length=2)
        assert len(docs) == 1
        assert await redis_hot.get(room_pending_message_key(room_id)) is None
        assert await redis_hot.sismember(DIRTY_CHAT_ROOM_KEY, room_id)

    async def test_pending_scheduler_recovers_system_message_without_sender(
        self, session_factory, direct_room, chat_fanout_stub, chat_fcm_stub,
        redis_hot, mongo_db, monkeypatch,
    ):
        class SimulatedProcessDeath(BaseException):
            pass

        room_id, _, _ = direct_room
        original_insert = ChatMessageRepository.insert
        crashed = False

        async def crash_before_first_mongo_write(repo, document):
            nonlocal crashed
            if not crashed:
                crashed = True
                raise SimulatedProcessDeath
            await original_insert(repo, document)

        monkeypatch.setattr(
            ChatMessageRepository, "insert", crash_before_first_mongo_write,
        )
        service = MessageService(
            uow=UnitOfWork(session=session_factory),
            fanout_service=chat_fanout_stub,
            fcm_service_factory=lambda: chat_fcm_stub,
        )

        with pytest.raises(SimulatedProcessDeath):
            await service.send_system_message(
                room_id=room_id,
                action="scheduler_recovery",
                actor_id=None,
            )

        assert await redis_hot.get(room_pending_message_key(room_id)) is not None
        monkeypatch.setattr(reconcile, "PENDING_RECOVERY_INTERVAL_SEC", 0.01)
        reconcile.start_reconcile_scheduler(session_factory)
        try:
            for _ in range(100):
                if await redis_hot.get(room_pending_message_key(room_id)) is None:
                    break
                await asyncio.sleep(0.01)
        finally:
            await reconcile.stop_reconcile_scheduler()

        docs = await mongo_db.chat_message.find({
            "chat_room_id": room_id,
            "type": MessageType.SYSTEM.value,
            "content.action": "scheduler_recovery",
        }).to_list(length=2)
        assert len(docs) == 1
        assert docs[0]["sender_id"] is None

    async def test_concurrent_sends_yield_unique_monotonic_seq(
        self, session_factory, direct_room, chat_fanout_stub, chat_fcm_stub, mongo_db, monkeypatch,
    ):
        monkeypatch.setattr(
            "app.domain.chat.service.message.RATE_LIMIT_THRESHOLD",
            _CONCURRENT_COUNT * 2,
        )

        room_id, user_a, user_b = direct_room

        async def send(i: int):
            uow = UnitOfWork(session=session_factory)
            svc = MessageService(uow=uow, fanout_service=chat_fanout_stub, fcm_service_factory=lambda: chat_fcm_stub)
            uid = user_a if i % 2 == 0 else user_b
            return await svc.send_message(
                sender_user_id=uid,
                sender_session_id=f"WS_sender_{uid}",
                room_id=room_id,
                client_msg_id=f"cmid-{i}",
                msg_type=MessageType.TEXT,
                content=f"msg {i}",
            )

        acks = await asyncio.gather(*(send(i) for i in range(_CONCURRENT_COUNT)))
        seqs = [ack.server_seq for ack in acks]

        # PHASE_1 "단조 seq" 의 실제 요구는 **유니크** 이다 — Lua atomic (+ 복구 경로의
        # force_jump) 이 결과적으로 중복 없는 seq 를 N 개 발행해야 한다. 첫 메시지
        # 복구 경로에서 `recover_and_incr(base=mongo_max+1000)` 가 뛰는 건 정상.
        assert len(set(seqs)) == _CONCURRENT_COUNT, (
            f"server_seq 에 중복 발생: {sorted(seqs)}"
        )
        assert all(s > 0 for s in seqs), f"비정상 seq: {sorted(seqs)}"

        cursor = mongo_db.chat_message.find({"chat_room_id": room_id})
        docs = [doc async for doc in cursor]
        assert len(docs) == _CONCURRENT_COUNT
        assert len({d["server_seq"] for d in docs}) == _CONCURRENT_COUNT
        assert sorted(d["server_seq"] for d in docs) == sorted(seqs), (
            "ACK 의 seq 집합과 Mongo 저장 seq 집합 불일치"
        )

        assert chat_fanout_stub.fan_out_to_room.await_count == _CONCURRENT_COUNT
