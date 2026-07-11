"""reconcile.recover_unread_for_user 단위 테스트.

unread self-heal 경로(재접속·Redis flush 후 복구). 절대 HSET 대신 baseline+delta Lua
(mark_read_unread)를 room 별로 호출해 count~write 창의 동시 HINCRBY 를 보존하는지, 부분 실패
시 hash 를 DEL 해 다음 재접속에서 재trigger 되게 하는지를 검증한다. (Lua 산술 자체는
test/integration/domain/chat/test_mark_read_unread_lua.py 에서 검증 — 여기선 orchestration.)
"""
import asyncio
import threading
from datetime import datetime, timezone
from typing import Any, cast
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

import app.domain.chat.worker.reconcile as rc
from app.core.chat.redis_key import read_sync_key, unread_key


pytestmark = pytest.mark.unit

_UID = "U_recover"


class TestDirtyRoomClaim:
    async def test_uses_atomic_lua_claim(self):
        script = AsyncMock(return_value=[0, "R_ORPHAN", "R_NEW"])

        with patch.object(rc.lua_scripts, "claim_dirty_rooms", script):
            rooms = await rc._claim_dirty_rooms(MagicMock(), "claim-token")

        assert rooms == (["R_ORPHAN", "R_NEW"], False)
        script.assert_awaited_once_with(
            keys=[
                rc.DIRTY_CHAT_ROOM_KEY,
                rc.DIRTY_CHAT_ROOM_PROCESSING_KEY,
                rc.DIRTY_CHAT_ROOM_PROCESSING_OWNER_KEY,
                rc.DIRTY_CHAT_ROOM_DEFERRED_KEY,
            ],
            args=[rc.RECONCILE_BATCH_SIZE, rc.RECONCILE_CLAIM_LEASE_MS, "claim-token"],
        )

    async def test_fails_closed_before_lua_registry_is_loaded(self):
        with (
            patch.object(rc.lua_scripts, "claim_dirty_rooms", None),
            pytest.raises(RuntimeError, match="로드되지 않았습니다"),
        ):
            await rc._claim_dirty_rooms(MagicMock(), "claim-token")


class TestDirtyRoomProcessingAck:
    @staticmethod
    def _dependencies(redis):
        message_repo = MagicMock()
        message_repo.find_last_by_rooms = AsyncMock(return_value={
            "R1": {"message_id": "M1", "server_seq": 1, "created_at": "now"},
        })
        room_repo = MagicMock()
        room_repo.update_last_message_if_greater = AsyncMock()

        async def get_redis():
            return redis

        return get_redis, message_repo, room_repo

    async def test_acknowledges_processing_only_after_sql_commit(self):
        redis = MagicMock()
        redis.scard = AsyncMock(return_value=0)
        redis.zcard = AsyncMock(return_value=1)
        get_redis, message_repo, room_repo = self._dependencies(redis)
        ack = AsyncMock(return_value=1)

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def commit(self):
                ack.assert_not_awaited()

        with (
            patch.object(rc, "get_redis_client", get_redis),
            patch.object(rc, "_claim_dirty_rooms", AsyncMock(return_value=(["R1"], False))),
            patch.object(rc, "_ack_dirty_rooms", ack),
            patch.object(rc, "ChatMessageRepository", return_value=message_repo),
            patch.object(rc, "ChatRoomRepository", return_value=room_repo),
            patch.object(rc, "_session_factory", lambda: Session()),
        ):
            assert await rc.reconcile_last_message_once() == 1

        ack.assert_awaited_once_with(ANY, ["R1"])

    async def test_commit_failure_keeps_processing_for_retry(self):
        redis = MagicMock()
        redis.scard = AsyncMock(return_value=0)
        redis.zcard = AsyncMock(return_value=1)
        get_redis, message_repo, room_repo = self._dependencies(redis)
        ack = AsyncMock(return_value=1)

        class Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def commit(self):
                raise RuntimeError("commit failed")

            async def rollback(self):
                return None

        with (
            patch.object(rc, "get_redis_client", get_redis),
            patch.object(rc, "_claim_dirty_rooms", AsyncMock(return_value=(["R1"], False))),
            patch.object(rc, "_ack_dirty_rooms", ack),
            patch.object(rc, "ChatMessageRepository", return_value=message_repo),
            patch.object(rc, "ChatRoomRepository", return_value=room_repo),
            patch.object(rc, "_session_factory", lambda: Session()),
        ):
            assert await rc.reconcile_last_message_once() == 0

        ack.assert_not_awaited()


class TestPendingMessageSweep:
    async def test_locks_room_before_recovering_orphan_pending(self):
        redis_hot = MagicMock()
        redis_hot.scan = AsyncMock(side_effect=[
            (17, ["room:pending_message:R1"]),
            (0, []),
        ])
        redis_dedupe = MagicMock()
        room_repo = MagicMock()
        room_repo.find_by_id_for_update = AsyncMock(return_value=object())
        recover = AsyncMock()

        class Session:
            active = False
            sync_session = MagicMock()

            async def __aenter__(self):
                self.active = True
                return self

            async def __aexit__(self, *args):
                self.active = False
                return False

            async def commit(self):
                recover.assert_awaited_once()

        session = Session()

        async def get_hot():
            return redis_hot

        async def get_dedupe():
            return redis_dedupe

        with (
            patch.object(rc, "get_redis_client", get_hot),
            patch.object(rc, "get_redis_dedupe_client", get_dedupe, create=True),
            patch.object(rc, "ChatRoomRepository", return_value=room_repo),
            patch.object(rc, "ChatMessageRepository", return_value=MagicMock()),
            patch.object(rc, "_recover_pending_message", recover, create=True),
            patch.object(rc, "_session_factory", lambda: session),
            patch.object(rc, "_pending_scan_cursor", 0, create=True),
        ):
            assert await rc.recover_pending_messages_once() == 1

        assert [call.kwargs["cursor"] for call in redis_hot.scan.await_args_list] == [0, 17]
        room_repo.find_by_id_for_update.assert_awaited_once_with("R1")
        assert session.active is False

    async def test_timeout_releases_room_and_continues_to_next_pending(self):
        redis_hot = MagicMock()
        redis_hot.scan = AsyncMock(return_value=(0, [
            "room:pending_message:R1", "room:pending_message:R2",
        ]))
        redis_dedupe = MagicMock()
        room_repo = MagicMock()
        room_repo.find_by_id_for_update = AsyncMock(return_value=object())
        never = asyncio.Event()
        recover_calls = 0

        async def recover(*_args, **_kwargs):
            nonlocal recover_calls
            recover_calls += 1
            if recover_calls == 1:
                await never.wait()

        class Session:
            sync_session = MagicMock()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False
            commit = AsyncMock()
            rollback = AsyncMock()

        async def get_hot():
            return redis_hot

        async def get_dedupe():
            return redis_dedupe

        with (
            patch.object(rc, "get_redis_client", get_hot),
            patch.object(rc, "get_redis_dedupe_client", get_dedupe),
            patch.object(rc, "ChatRoomRepository", return_value=room_repo),
            patch.object(rc, "ChatMessageRepository", return_value=MagicMock()),
            patch.object(rc, "_recover_pending_message", recover),
            patch.object(rc, "_session_factory", lambda: Session()),
            patch.object(rc, "_pending_scan_cursor", 0),
            patch.object(rc, "PENDING_RECOVERY_CANCEL_AFTER_SEC", 0.01, create=True),
        ):
            with pytest.raises(rc.PendingRecoveryBatchError):
                await rc.recover_pending_messages_once()

        assert recover_calls == 2

    async def test_unknown_room_pending_is_deleted(self):
        redis_hot = MagicMock()
        redis_hot.scan = AsyncMock(return_value=(0, ["room:pending_message:MISSING"]))
        redis_hot.delete = AsyncMock()
        redis_dedupe = MagicMock()
        room_repo = MagicMock()
        room_repo.find_by_id_for_update = AsyncMock(return_value=None)

        class Session:
            sync_session = MagicMock()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False
            commit = AsyncMock()
            rollback = AsyncMock()

        async def get_hot():
            return redis_hot

        async def get_dedupe():
            return redis_dedupe

        with (
            patch.object(rc, "get_redis_client", get_hot),
            patch.object(rc, "get_redis_dedupe_client", get_dedupe),
            patch.object(rc, "ChatRoomRepository", return_value=room_repo),
            patch.object(rc, "ChatMessageRepository", return_value=MagicMock()),
            patch.object(rc, "_session_factory", lambda: Session()),
            patch.object(rc, "_pending_scan_cursor", 0),
        ):
            assert await rc.recover_pending_messages_once() == 0

        redis_hot.delete.assert_awaited_once_with("room:pending_message:MISSING")

    async def test_room_lock_timeout_continues_to_next_pending(self):
        redis_hot = MagicMock()
        redis_hot.scan = AsyncMock(return_value=(0, [
            "room:pending_message:R1", "room:pending_message:R2",
        ]))
        redis_dedupe = MagicMock()
        never = asyncio.Event()
        lock_calls = 0

        async def lock_room(_room_id):
            nonlocal lock_calls
            lock_calls += 1
            if lock_calls == 1:
                await never.wait()
            return object()

        room_repo = MagicMock()
        room_repo.find_by_id_for_update = lock_room

        class Session:
            sync_session = MagicMock()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False
            commit = AsyncMock()
            rollback = AsyncMock()

        async def get_hot():
            return redis_hot

        async def get_dedupe():
            return redis_dedupe

        with (
            patch.object(rc, "get_redis_client", get_hot),
            patch.object(rc, "get_redis_dedupe_client", get_dedupe),
            patch.object(rc, "ChatRoomRepository", return_value=room_repo),
            patch.object(rc, "ChatMessageRepository", return_value=MagicMock()),
            patch.object(rc, "_recover_pending_message", AsyncMock()),
            patch.object(rc, "_session_factory", lambda: Session()),
            patch.object(rc, "_pending_scan_cursor", 0),
            patch.object(rc, "PENDING_RECOVERY_CANCEL_AFTER_SEC", 0.01),
        ):
            with pytest.raises(rc.PendingRecoveryBatchError):
                await asyncio.wait_for(
                    rc.recover_pending_messages_once(), timeout=0.1,
                )

        assert lock_calls == 2

    async def test_stop_drains_cancelled_recovery_task(self):
        started = asyncio.Event()

        async def running():
            started.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(running())
        await started.wait()
        event = asyncio.Event()
        with (
            patch.object(rc, "_reconcile_task", None),
            patch.object(rc, "_pending_recovery_task", task),
            patch.object(rc, "_stop_event", event),
            patch.object(rc, "RECONCILE_SHUTDOWN_GRACE_SEC", 0.01),
        ):
            await rc.stop_reconcile_scheduler()

        assert task.done()
        assert task.cancelled()

    async def test_cancel_force_invalidates_without_late_task_and_continues(self):
        redis_hot = MagicMock()
        redis_hot.scan = AsyncMock(return_value=(0, [
            "room:pending_message:R1", "room:pending_message:R2",
        ]))
        redis_dedupe = MagicMock()
        recover_never = asyncio.Event()
        recover_calls = 0
        sessions = []

        async def recover(*_args, **_kwargs):
            nonlocal recover_calls
            recover_calls += 1
            if recover_calls == 1:
                await recover_never.wait()

        class Session:
            def __init__(self):
                self.index = len(sessions)
                sessions.append(self)
                self.sync_session = MagicMock()

            commit = AsyncMock()

        async def get_hot():
            return redis_hot

        async def get_dedupe():
            return redis_dedupe

        room_repo = MagicMock()
        room_repo.find_by_id_for_update = AsyncMock(return_value=object())
        with (
            patch.object(rc, "get_redis_client", get_hot),
            patch.object(rc, "get_redis_dedupe_client", get_dedupe),
            patch.object(rc, "ChatRoomRepository", return_value=room_repo),
            patch.object(rc, "ChatMessageRepository", return_value=MagicMock()),
            patch.object(rc, "_recover_pending_message", recover),
            patch.object(rc, "_session_factory", lambda: Session()),
            patch.object(rc, "_pending_scan_cursor", 0),
            patch.object(rc, "PENDING_RECOVERY_CANCEL_AFTER_SEC", 0.01),
        ):
            with pytest.raises(rc.PendingRecoveryBatchError):
                await asyncio.wait_for(
                    rc.recover_pending_messages_once(), timeout=0.15,
                )

        assert recover_calls == 2
        sessions[0].sync_session.invalidate.assert_called_once_with()
        sessions[0].sync_session.close.assert_not_called()
        sessions[1].sync_session.close.assert_called_once_with()

    async def test_oversized_scan_page_keeps_backlog_bounded(self):
        keys = [f"room:pending_message:R{i}" for i in range(200)]
        redis_hot = MagicMock()
        redis_hot.scan = AsyncMock(return_value=(17, keys))

        with (
            patch.object(rc, "get_redis_client", AsyncMock(return_value=redis_hot)),
            patch.object(rc, "get_redis_dedupe_client", AsyncMock(return_value=MagicMock())),
            patch.object(rc, "ChatMessageRepository", return_value=MagicMock()),
            patch.object(rc, "_recover_pending_room", AsyncMock(return_value=True)),
            patch.object(rc, "_session_factory", MagicMock()),
            patch.object(rc, "_pending_scan_cursor", 0),
            patch.object(rc, "_pending_key_backlog", rc.deque()),
            patch.object(rc, "_pending_key_backlog_set", set()),
            patch.object(rc, "PENDING_DISCOVERY_BACKLOG_LIMIT", 25, create=True),
        ):
            assert await rc.recover_pending_messages_once() == 5
            assert len(rc._pending_key_backlog) <= 20

    async def test_worker_cancel_drains_motor_executor_before_invalidate(self):
        from bson import json_util

        pending = {
            "_id": "MSG_MOTOR_DRAIN",
            "chat_room_id": "R1",
            "server_seq": 1,
            "sender_id": None,
            "client_msg_id": None,
            "type": "system",
            "content": "drain",
            "created_at": datetime.now(timezone.utc),
            "edited_at": None,
            "deleted_at": None,
        }
        redis_hot = MagicMock()
        redis_hot.get = AsyncMock(return_value=json_util.dumps(pending))
        redis_hot.delete = AsyncMock()
        redis_hot.sadd = AsyncMock()
        redis_dedupe = MagicMock()
        insert_started = asyncio.Event()
        thread_release = threading.Event()
        invalidated = MagicMock()

        async def motor_insert(_document):
            insert_started.set()
            await asyncio.to_thread(thread_release.wait)

        message_repo = MagicMock()
        message_repo.insert = AsyncMock(side_effect=motor_insert)

        class Session:
            def __init__(self):
                self.sync_session = MagicMock()
                self.sync_session.invalidate = invalidated

            commit = AsyncMock()

        session = Session()
        room_repo = MagicMock()
        room_repo.find_by_id_for_update = AsyncMock(return_value=object())
        with patch.object(rc, "ChatRoomRepository", return_value=room_repo):
            task = asyncio.create_task(rc._recover_pending_room(
                cast(Any, lambda: session),
                redis_hot, redis_dedupe, message_repo, "R1",
            ))
            await insert_started.wait()
            task.cancel()
            await asyncio.sleep(0.01)

            assert not task.done()
            invalidated.assert_not_called()
            thread_release.set()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=0.2)

        invalidated.assert_called_once_with()
        redis_hot.delete.assert_not_awaited()


class _FakeSession:
    active = False

    async def __aenter__(self):
        self.active = True
        return self

    async def __aexit__(self, *a):
        self.active = False
        return False


def _patches(*, last_reads, baselines, residuals, lua_side_effect, generation_error=None):
    """recover_unread_for_user 의 외부 의존성 패치 묶음 반환."""
    redis = MagicMock(name="redis")
    redis.hget = AsyncMock(side_effect=lambda key, field: baselines.get(field))
    session = _FakeSession()

    async def _get_generation(_key):
        assert session.active, "membership lock must cover generation capture"
        if generation_error is not None:
            raise generation_error
        return None

    redis.get = AsyncMock(side_effect=_get_generation)
    redis.delete = AsyncMock(return_value=1)

    async def _get_redis():
        return redis

    async def _count(*, chat_room_id, after_seq, limit):
        result = residuals[chat_room_id]
        if isinstance(result, BaseException):
            raise result
        return result

    msg_repo = MagicMock()
    msg_repo.count_after_seq = _count
    member_repo = MagicMock()
    member_repo.find_last_read_seqs = AsyncMock(return_value=last_reads)
    redis.member_repo = member_repo

    lua = MagicMock()
    lua.mark_read_unread = AsyncMock(side_effect=lua_side_effect)

    ctx = [
        patch.object(rc, "get_redis_client", _get_redis),
        patch.object(rc, "ChatMessageRepository", return_value=msg_repo),
        patch.object(rc, "ChatRoomMemberRepository", return_value=member_repo),
        patch.object(rc, "lua_scripts", lua),
        patch.object(rc, "_session_factory", lambda: session),
    ]
    return redis, lua, ctx


async def _run(ctx_managers):
    for c in ctx_managers:
        c.start()
    try:
        return await rc.recover_unread_for_user(_UID)
    finally:
        for c in reversed(ctx_managers):
            c.stop()


class TestRecoverUnread:
    async def test_passes_baseline_and_residual_to_lua_per_room(self):
        """room 별로 (room_id, residual, baseline, cap) 인자로 baseline+delta Lua 호출."""
        async def lua_stub(keys, args):
            _room, residual, _baseline, cap, read_seq, _allow_equal, _generation = args
            return [min(residual, cap), 1, read_seq]  # 스텁: residual 반영

        redis, lua, ctx = _patches(
            last_reads={"R1": 10, "R2": 20},
            baselines={"R1": "3", "R2": None},   # R2 는 baseline 부재 → 0 취급
            residuals={"R1": 5, "R2": 2},
            lua_side_effect=lua_stub,
        )
        counts = await _run(ctx)

        assert counts == {"R1": 5, "R2": 2}
        redis.member_repo.find_last_read_seqs.assert_awaited_once_with(
            _UID,
            room_ids=None,
            for_share=True,
        )
        # baseline 스냅샷(HGET)이 방마다 호출됐는지
        redis.hget.assert_any_await(unread_key(_UID), "R1")
        redis.hget.assert_any_await(unread_key(_UID), "R2")
        # Lua 인자에 baseline 이 정확히 전달됐는지 (부재는 0)
        calls = {c.kwargs["args"][0]: c.kwargs["args"] for c in lua.mark_read_unread.await_args_list}
        assert calls["R1"] == ["R1", 5, 3, rc.UNREAD_COUNT_CAP, 10, 1, 0]
        assert calls["R2"] == ["R2", 2, 0, rc.UNREAD_COUNT_CAP, 20, 1, 0]
        for call in lua.mark_read_unread.await_args_list:
            room_id = call.kwargs["args"][0]
            assert call.kwargs["keys"] == [
                unread_key(_UID), read_sync_key(_UID),
                rc.room_members_gen_key(room_id),
            ]

    async def test_caps_residual_snapshot_at_limit(self):
        """DB 잔여가 cap 을 넘으면 residual 스냅샷 단계에서 999 로 clamp 되어 전달된다."""
        async def lua_stub(keys, args):
            return [args[1], 1, args[4]]

        _redis, lua, ctx = _patches(
            last_reads={"R1": 0},
            baselines={"R1": None},
            residuals={"R1": 100_000},   # count_after_seq 원값 (min(raw, cap) 로 clamp 기대)
            lua_side_effect=lua_stub,
        )
        counts = await _run(ctx)

        assert counts == {"R1": rc.UNREAD_COUNT_CAP}
        assert lua.mark_read_unread.await_args_list[0].kwargs["args"][1] == rc.UNREAD_COUNT_CAP

    async def test_partial_lua_failure_deletes_hash(self):
        """Lua 반영 중 실패 → partial state 방지 위해 hash DEL 후 빈 dict 반환 (재trigger 유도)."""
        async def lua_flaky(keys, args):
            if args[0] == "R2":
                raise RuntimeError("redis blip")
            return [args[1], 1, args[4]]

        redis, _lua, ctx = _patches(
            last_reads={"R1": 0, "R2": 0},
            baselines={"R1": None, "R2": None},
            residuals={"R1": 1, "R2": 1},
            lua_side_effect=lua_flaky,
        )
        counts = await _run(ctx)

        assert counts == {}
        redis.delete.assert_awaited_once_with(unread_key(_UID))

    async def test_partial_count_failure_skips_lua_and_deletes_hashes(self):
        """방 하나의 Mongo count 실패도 partial HASH를 만들지 않고 전체 재시도한다."""
        redis, lua, ctx = _patches(
            last_reads={"R1": 10, "R2": 20},
            baselines={"R1": None, "R2": None},
            residuals={"R1": 1, "R2": RuntimeError("mongo blip")},
            lua_side_effect=lambda keys, args: [args[1], 1, args[4]],
        )

        counts = await _run(ctx)

        assert counts == {}
        lua.mark_read_unread.assert_not_awaited()
        redis.delete.assert_awaited_once_with(unread_key(_UID))

    async def test_generation_snapshot_failure_deletes_unread_only(self):
        redis, lua, ctx = _patches(
            last_reads={"R1": 10},
            baselines={"R1": None},
            residuals={"R1": 1},
            lua_side_effect=lambda keys, args: [args[1], 1, args[4]],
            generation_error=RuntimeError("redis blip"),
        )

        counts = await _run(ctx)

        assert counts == {}
        redis.hget.assert_not_awaited()
        lua.mark_read_unread.assert_not_awaited()
        redis.delete.assert_awaited_once_with(unread_key(_UID))

    async def test_no_active_rooms_skips(self):
        """활성 방이 없으면 Redis/Lua 를 건드리지 않고 빈 dict."""
        redis, lua, ctx = _patches(
            last_reads={},
            baselines={},
            residuals={},
            lua_side_effect=lambda keys, args: 0,
        )
        counts = await _run(ctx)

        assert counts == {}
        redis.hget.assert_not_awaited()
        lua.mark_read_unread.assert_not_awaited()
