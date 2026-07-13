"""WithdrawService.purge e2e 통합 테스트 (RDB + Mongo + 인박스 cascade).

소프트 탈뙤 → 영구 삭제 흐름의 분산 정합성 검증. unit 테스트가 mock 으로 검증할 수 없는
영역:
    - `_purge_rdb` 의 SELECT FOR UPDATE + status 분기 + hard_delete 실 트랜잭션
    - `_purge_external` 단계별 best-effort 가 실 mongo 컬렉션에 반영
    - 인박스 cascade — `recipient_id == user_id` OR `actor_id == user_id` 매칭 모두 삭제
    - STALE_DOC outcome (cancel 후 worker 진입) — RDB 보존 + doc 만 청소

검증 매트릭스:

    | 시나리오                | RDB user | Mongo user data | 인박스 cascade |
    |---|---|---|---|
    | 정상 purge (INACTIVE)   | hard delete | drop          | recipient/actor 삭제 |
    | 미존재 user (NO_USER)   | -           | drop          | cascade 호출 (idempotent) |
    | STALE_DOC (ACTIVE)      | 보존        | doc 만 청소   | cascade 호출 안 함 |
"""
import pytest
from sqlalchemy import select

from app.domain.auth.model.user import User, UserStatus
from app.domain.auth.model.withdrawal_request import WithdrawalRequest
from app.domain.auth.service import withdraw as withdraw_module
from app.domain.notification.model.inbox import (
    InboxItem,
    InboxItemType,
    TargetType,
)


pytestmark = pytest.mark.integration


class TestPurgeDeletedOutcome:
    """status=INACTIVE 인 user 의 영구 삭제 — RDB hard delete + Mongo 정리 + 인박스 cascade."""

    async def test_hard_deletes_user_from_rdb(
        self, withdraw_service, session_factory, seed_users,
    ):
        user_id, *_ = await seed_users(1)
        await _set_inactive(session_factory, user_id)

        await withdraw_service.purge(user_id=user_id)

        async with session_factory() as session:
            result = await session.execute(
                select(User).where(User.user_id == user_id)
            )
            assert result.scalar_one_or_none() is None

    async def test_cascade_deletes_recipient_and_actor_inbox_items(
        self, withdraw_service, session_factory, seed_users, mongo_db,
    ):
        """탈뙤 user 가 받은(recipient) 항목 + 보낸(actor) 항목 모두 삭제. 무관한 항목 보존."""
        target_user, other_user = await seed_users(2)
        await _set_inactive(session_factory, target_user)

        await InboxItem(
            recipient_id=target_user, actor_id=other_user,
            type=InboxItemType.FEED_LIKE,
            target_type=TargetType.FEED_POST,
            target_id="FDP_1", actor_name="x",
        ).insert()
        await InboxItem(
            recipient_id=other_user, actor_id=target_user,
            type=InboxItemType.FEED_LIKE,
            target_type=TargetType.FEED_POST,
            target_id="FDP_2", actor_name="x",
        ).insert()
        await InboxItem(
            recipient_id=other_user, actor_id="USER_unrelated",
            type=InboxItemType.FEED_LIKE,
            target_type=TargetType.FEED_POST,
            target_id="FDP_3", actor_name="x",
        ).insert()

        await withdraw_service.purge(user_id=target_user)

        coll = InboxItem.get_motor_collection()
        assert await coll.count_documents({}) == 1
        remaining = await coll.find_one({})
        assert remaining["actor_id"] == "USER_unrelated"

    async def test_cleans_withdrawal_request_doc(
        self, withdraw_service, session_factory, seed_users,
    ):
        user_id, *_ = await seed_users(1)
        await _set_inactive(session_factory, user_id)

        from datetime import datetime, timedelta, timezone
        await WithdrawalRequest(
            user_id=user_id,
            requested_at=datetime.now(timezone.utc),
            scheduled_purge_at=datetime.now(timezone.utc) - timedelta(days=1),
        ).insert()

        await withdraw_service.purge(user_id=user_id)

        coll = WithdrawalRequest.get_motor_collection()
        assert await coll.count_documents({"user_id": user_id}) == 0


class TestPurgeStaleDocOutcome:
    """status != INACTIVE (cancel 복구 또는 dual-write 잔존) → 외부 리소스 보존, doc 만 청소.

    race-free 안전장치의 핵심: cancel 이 먼저 commit 되어 status=ACTIVE 인 user 의 외부
    데이터를 잘못 날리지 않음.
    """

    async def test_active_user_external_data_preserved(
        self, withdraw_service, session_factory, seed_users, mongo_db,
        storage_mock,
    ):
        """status=ACTIVE → RDB hard delete / Storage cleanup / 인박스 cascade 모두 skip."""
        user_id, other_user = await seed_users(2)

        await InboxItem(
            recipient_id=user_id, actor_id=other_user,
            type=InboxItemType.FEED_LIKE,
            target_type=TargetType.FEED_POST,
            target_id="FDP_1", actor_name="x",
        ).insert()

        from datetime import datetime, timedelta, timezone
        await WithdrawalRequest(
            user_id=user_id,
            requested_at=datetime.now(timezone.utc),
            scheduled_purge_at=datetime.now(timezone.utc) - timedelta(days=1),
        ).insert()

        await withdraw_service.purge(user_id=user_id)

        async with session_factory() as session:
            result = await session.execute(
                select(User).where(User.user_id == user_id)
            )
            user = result.scalar_one_or_none()
            assert user is not None
            assert user.status == UserStatus.ACTIVE

        inbox_coll = InboxItem.get_motor_collection()
        assert await inbox_coll.count_documents({"recipient_id": user_id}) == 1

        storage_mock.delete_by_prefix.assert_not_awaited()

        wr_coll = WithdrawalRequest.get_motor_collection()
        assert await wr_coll.count_documents({"user_id": user_id}) == 0


class TestPurgeNoUserOutcome:
    """RDB 에 user 없음 (이전 사이클 외부 정리 잔존) → 외부 정리만 idempotent 진행."""

    async def test_runs_external_cleanup_idempotently(
        self, withdraw_service, mongo_db, storage_mock, redis_cache_mock,
    ):
        await withdraw_service.purge(user_id="USER_ghost")

        inbox_coll = InboxItem.get_motor_collection()
        assert await inbox_coll.count_documents({}) == 0

        storage_mock.delete_by_prefix.assert_awaited_once_with("USER_ghost")
        redis_cache_mock.assert_awaited_once_with("USER_ghost")


class TestPurgeRetryMarker:
    async def test_real_redis_failure_retains_marker_then_retry_removes_all_chat_keys(
        self, withdraw_service, session_factory, seed_users, monkeypatch,
    ):
        import os
        from datetime import datetime, timedelta, timezone
        from unittest.mock import AsyncMock

        from redis import asyncio as aioredis

        from app.core.chat.redis_key import (
            read_sync_key,
            unread_key,
            unread_recovery_required_key,
            unread_watermark_key,
        )
        from app.domain.chat.service import user_purge_cache as chat_purge_module
        from app.domain.chat.service.user_purge_cache import UserPurgeCacheService

        [user_id] = await seed_users(1)
        await _set_inactive(session_factory, user_id)
        await WithdrawalRequest(
            user_id=user_id,
            requested_at=datetime.now(timezone.utc),
            scheduled_purge_at=datetime.now(timezone.utc) - timedelta(days=1),
        ).insert()
        redis = aioredis.from_url(os.environ["REDIS_TEST_URL"], decode_responses=True)
        keys = (
            unread_key(user_id),
            read_sync_key(user_id),
            unread_watermark_key(user_id),
            unread_recovery_required_key(user_id),
        )
        for key in keys:
            await redis.hset(key, mapping={"room": "1"})
        withdraw_service._chat_purge = UserPurgeCacheService(AsyncMock())

        async def unavailable_redis():
            raise RuntimeError("injected redis outage")

        async def actual_redis():
            return redis

        monkeypatch.setattr(chat_purge_module, "get_redis_client", unavailable_redis)
        with pytest.raises(RuntimeError, match="외부 정리 미완료"):
            await withdraw_service.purge(user_id=user_id)

        assert await WithdrawalRequest.get_motor_collection().count_documents({"user_id": user_id}) == 1
        assert all([await redis.exists(key) for key in keys])

        monkeypatch.setattr(chat_purge_module, "get_redis_client", actual_redis)
        await withdraw_service.purge(user_id=user_id)

        assert await WithdrawalRequest.get_motor_collection().count_documents({"user_id": user_id}) == 0
        assert not any([await redis.exists(key) for key in keys])
        await redis.aclose()

    async def test_stale_worker_preserves_new_withdrawal_generation_and_rdb_user(
        self, withdraw_service, session_factory, seed_users, storage_mock,
    ):
        from datetime import datetime, timedelta, timezone

        [user_id] = await seed_users(1)
        await _set_inactive(session_factory, user_id)
        old_requested_at = datetime.now(timezone.utc).replace(microsecond=0)
        await WithdrawalRequest(
            user_id=user_id,
            generation_id="G1",
            requested_at=old_requested_at,
            scheduled_purge_at=old_requested_at - timedelta(days=1),
        ).insert()

        await withdraw_service.cancel_withdraw(user_id=user_id)
        await withdraw_service.request_withdraw(user_id=user_id)
        new_marker = await WithdrawalRequest.find_one(WithdrawalRequest.user_id == user_id)
        assert new_marker is not None
        assert new_marker.generation_id not in (None, "G1")
        await WithdrawalRequest.get_motor_collection().update_one(
            {"user_id": user_id},
            {"$set": {"requested_at": old_requested_at}},
        )

        await withdraw_service.purge(
            user_id=user_id,
            expected_generation_id="G1",
            expected_requested_at=old_requested_at,
        )

        async with session_factory() as session:
            user = await session.scalar(select(User).where(User.user_id == user_id))
        current_marker = await WithdrawalRequest.find_one(WithdrawalRequest.user_id == user_id)
        assert user is not None
        assert user.status == UserStatus.INACTIVE
        assert current_marker is not None
        assert current_marker.generation_id == new_marker.generation_id
        assert current_marker.requested_at == old_requested_at
        storage_mock.delete_by_prefix.assert_not_awaited()

    async def test_mongo_failure_retains_marker_and_next_attempt_finishes_cleanup(
        self, withdraw_service, session_factory, seed_users, mongo_db, monkeypatch,
    ):
        from datetime import datetime, timedelta, timezone

        [user_id] = await seed_users(1)
        await _set_inactive(session_factory, user_id)
        await WithdrawalRequest(
            user_id=user_id,
            requested_at=datetime.now(timezone.utc),
            scheduled_purge_at=datetime.now(timezone.utc) - timedelta(days=1),
        ).insert()
        await mongo_db["tripmate_image"].insert_one({
            "user_id": user_id,
            "image_id": "TMI_retry",
            "image_url": "https://storage.example.com/retry.jpg",
            "timestamp": datetime.now(timezone.utc),
        })

        original_document = withdraw_module.TripmateImage

        class FailingTripmateImage:
            @staticmethod
            def find(_query):
                return _RaisingDeleteQuery()

        monkeypatch.setattr(withdraw_module, "TripmateImage", FailingTripmateImage)

        with pytest.raises(RuntimeError, match="외부 정리 미완료"):
            await withdraw_service.purge(user_id=user_id)

        assert await WithdrawalRequest.get_motor_collection().count_documents({"user_id": user_id}) == 1
        assert await mongo_db["tripmate_image"].count_documents({"user_id": user_id}) == 1

        monkeypatch.setattr(withdraw_module, "TripmateImage", original_document)
        await withdraw_service.purge(user_id=user_id)

        assert await WithdrawalRequest.get_motor_collection().count_documents({"user_id": user_id}) == 0
        assert await mongo_db["tripmate_image"].count_documents({"user_id": user_id}) == 0

    async def test_storage_failure_retains_marker_until_idempotent_retry_succeeds(
        self, withdraw_service, session_factory, seed_users, storage_mock,
    ):
        from datetime import datetime, timedelta, timezone

        [user_id] = await seed_users(1)
        await _set_inactive(session_factory, user_id)
        await WithdrawalRequest(
            user_id=user_id,
            requested_at=datetime.now(timezone.utc),
            scheduled_purge_at=datetime.now(timezone.utc) - timedelta(days=1),
        ).insert()
        storage_mock.delete_by_prefix.side_effect = RuntimeError("injected storage outage")

        with pytest.raises(RuntimeError, match="외부 정리 미완료"):
            await withdraw_service.purge(user_id=user_id)

        assert await WithdrawalRequest.get_motor_collection().count_documents({"user_id": user_id}) == 1

        storage_mock.delete_by_prefix.side_effect = None
        await withdraw_service.purge(user_id=user_id)

        assert await WithdrawalRequest.get_motor_collection().count_documents({"user_id": user_id}) == 0
        assert storage_mock.delete_by_prefix.await_count == 2


class _RaisingDeleteQuery:
    async def delete(self):
        raise RuntimeError("injected mongo outage")


async def _set_inactive(session_factory, user_id: str) -> None:
    """seed_users 가 만든 ACTIVE user 를 INACTIVE 로 전환."""
    async with session_factory() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalar_one()
        user.status = UserStatus.INACTIVE
        await session.commit()
