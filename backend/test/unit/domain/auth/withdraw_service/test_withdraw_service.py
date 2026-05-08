"""WithdrawService — 30일 유예 탈퇴 정책 단위 테스트.

검증 대상:
    - `request_withdraw`: ACTIVE → INACTIVE + Mongo upsert + scheduled_purge_at 30일 후
    - `cancel_withdraw`: INACTIVE → ACTIVE + Mongo doc 청소. doc 청소 실패 swallow
    - `purge`: 3개 outcome 분기 (DELETED / NO_USER / STALE_DOC)
    - `_purge_external`: Mongo 5종 / Storage / Redis / 알림 cascade / withdrawal_request doc
      각 단계 best-effort + 알림 cascade 호출 검증

`_purge_rdb` outcome 분기는 service 의 internal 상태 결정 — 본 테스트는 SELECT FOR UPDATE +
status 검사를 user_repo_mock 으로 시뮬레이션.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.auth.model.user import UserStatus
from app.domain.auth.model.withdrawal_request import WITHDRAWAL_GRACE_PERIOD_DAYS
from app.domain.auth.service.exception import (
    WithdrawalAlreadyRequestedError,
    WithdrawalNotPendingError,
)
from app.domain.auth.service.withdraw import _PurgeOutcome

from test.unit.domain.auth.withdraw_service.model_factory import UserFactory


# ──────────────────────────────────────────────────────────────────
# request_withdraw — soft 탈퇴 (ACTIVE → INACTIVE + Mongo upsert)
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRequestWithdraw:
    """Tests for WithdrawService.request_withdraw."""

    async def test_changes_status_to_inactive(
        self, service, user_repo_mock, withdrawal_request_repo_mock,
    ):
        user = UserFactory.create(user_id="USER_a", status=UserStatus.ACTIVE)
        user_repo_mock.find_by_id.return_value = user

        await service.request_withdraw(user_id="USER_a")

        assert user.status == UserStatus.INACTIVE
        user_repo_mock.update.assert_awaited_once_with(user)

    async def test_upserts_mongo_doc_after_status_change(
        self, service, user_repo_mock, withdrawal_request_repo_mock,
    ):
        """status 변경 후 Mongo upsert. user_id / requested_at / scheduled_purge_at 인자 검증."""
        user = UserFactory.create(user_id="USER_a", status=UserStatus.ACTIVE)
        user_repo_mock.find_by_id.return_value = user

        await service.request_withdraw(user_id="USER_a")

        withdrawal_request_repo_mock.upsert.assert_awaited_once()
        kwargs = withdrawal_request_repo_mock.upsert.await_args.kwargs
        assert kwargs["user_id"] == "USER_a"
        assert isinstance(kwargs["requested_at"], datetime)
        assert isinstance(kwargs["scheduled_purge_at"], datetime)

    async def test_returns_purge_at_30_days_ahead(
        self, service, user_repo_mock,
    ):
        """30일 grace period 정확성 — 사용자 표시용 시각 반환."""
        user = UserFactory.create(status=UserStatus.ACTIVE)
        user_repo_mock.find_by_id.return_value = user

        before = datetime.now(timezone.utc)
        purge_at = await service.request_withdraw(user_id=user.user_id)
        after = datetime.now(timezone.utc)

        # 30일 ± 1초 허용 (테스트 실행 시간 흔들림)
        expected_min = before + timedelta(days=WITHDRAWAL_GRACE_PERIOD_DAYS) - timedelta(seconds=1)
        expected_max = after + timedelta(days=WITHDRAWAL_GRACE_PERIOD_DAYS) + timedelta(seconds=1)
        assert expected_min <= purge_at <= expected_max

    async def test_raises_when_user_not_found(
        self, service, user_repo_mock, withdrawal_request_repo_mock,
    ):
        user_repo_mock.find_by_id.return_value = None

        with pytest.raises(ValueError, match="존재하지 않는"):
            await service.request_withdraw(user_id="USER_x")

        user_repo_mock.update.assert_not_awaited()
        withdrawal_request_repo_mock.upsert.assert_not_awaited()

    async def test_raises_when_already_inactive(
        self, service, user_repo_mock, withdrawal_request_repo_mock,
    ):
        """이미 INACTIVE — 중복 요청 차단."""
        user = UserFactory.create(status=UserStatus.INACTIVE)
        user_repo_mock.find_by_id.return_value = user

        with pytest.raises(WithdrawalAlreadyRequestedError):
            await service.request_withdraw(user_id=user.user_id)

        user_repo_mock.update.assert_not_awaited()
        withdrawal_request_repo_mock.upsert.assert_not_awaited()


# ──────────────────────────────────────────────────────────────────
# cancel_withdraw — INACTIVE → ACTIVE + Mongo doc 청소
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestCancelWithdraw:
    """Tests for WithdrawService.cancel_withdraw."""

    async def test_changes_status_to_active_and_deletes_doc(
        self, service, user_repo_mock, withdrawal_request_repo_mock,
    ):
        user = UserFactory.create(user_id="USER_a", status=UserStatus.INACTIVE)
        user_repo_mock.find_by_id_for_update.return_value = user

        await service.cancel_withdraw(user_id="USER_a")

        assert user.status == UserStatus.ACTIVE
        user_repo_mock.update.assert_awaited_once_with(user)
        withdrawal_request_repo_mock.delete_by_user_id.assert_awaited_once_with("USER_a")

    async def test_doc_cleanup_failure_swallowed(
        self, service, user_repo_mock, withdrawal_request_repo_mock,
    ):
        """Mongo doc 정리 실패 → swallow + 로그. status 는 이미 ACTIVE 라 다음 worker
        STALE_DOC 가드가 정리. raise 없이 정상 종료."""
        user = UserFactory.create(status=UserStatus.INACTIVE)
        user_repo_mock.find_by_id_for_update.return_value = user
        withdrawal_request_repo_mock.delete_by_user_id.side_effect = RuntimeError("mongo down")

        # raise 없이 정상 종료
        await service.cancel_withdraw(user_id=user.user_id)

        assert user.status == UserStatus.ACTIVE  # RDB 는 이미 commit

    async def test_raises_when_user_not_found(
        self, service, user_repo_mock, withdrawal_request_repo_mock,
    ):
        user_repo_mock.find_by_id_for_update.return_value = None

        with pytest.raises(ValueError, match="존재하지 않는"):
            await service.cancel_withdraw(user_id="USER_x")

        withdrawal_request_repo_mock.delete_by_user_id.assert_not_awaited()

    async def test_raises_when_not_inactive(
        self, service, user_repo_mock, withdrawal_request_repo_mock,
    ):
        """이미 ACTIVE 상태 — cancel 할 게 없음."""
        user = UserFactory.create(status=UserStatus.ACTIVE)
        user_repo_mock.find_by_id_for_update.return_value = user

        with pytest.raises(WithdrawalNotPendingError):
            await service.cancel_withdraw(user_id=user.user_id)

        user_repo_mock.update.assert_not_awaited()
        withdrawal_request_repo_mock.delete_by_user_id.assert_not_awaited()


# ──────────────────────────────────────────────────────────────────
# purge — entry point + outcome 분기 (DELETED / NO_USER / STALE_DOC)
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPurge:
    """Tests for WithdrawService.purge — `_purge_rdb` outcome 별 후속 흐름 분기.

    `_purge_rdb` 의 row lock 자체는 SELECT FOR UPDATE 와 status 검사로 시뮬레이션 (mock).
    """

    async def test_deleted_outcome_proceeds_to_external_cleanup(
        self, service, user_repo_mock,
        inbox_service_mock, withdrawal_request_repo_mock,
    ):
        """status==INACTIVE → hard_delete_by_id + 외부 정리 진행 → 알림 cascade 호출."""
        user = UserFactory.create(user_id="USER_a", status=UserStatus.INACTIVE)
        user_repo_mock.find_by_id_for_update.return_value = user

        await service.purge(user_id="USER_a")

        user_repo_mock.hard_delete_by_id.assert_awaited_once_with("USER_a")
        inbox_service_mock.cascade_user_withdrawn.assert_awaited_once_with("USER_a")
        # withdrawal_request doc 도 마지막에 청소
        withdrawal_request_repo_mock.delete_by_user_id.assert_awaited_once_with("USER_a")

    async def test_no_user_outcome_still_runs_external_cleanup(
        self, service, user_repo_mock, inbox_service_mock,
    ):
        """RDB 에 user 없음 (이전 사이클 외부 정리 잔존) → 외부 정리 idempotent 재시도."""
        user_repo_mock.find_by_id_for_update.return_value = None

        await service.purge(user_id="USER_a")

        user_repo_mock.hard_delete_by_id.assert_not_awaited()  # 이미 삭제됨
        inbox_service_mock.cascade_user_withdrawn.assert_awaited_once_with("USER_a")

    async def test_stale_doc_outcome_skips_external(
        self, service, user_repo_mock,
        inbox_service_mock, withdrawal_request_repo_mock,
        beanie_stubs, storage_mock, invalidate_cache_mock,
    ):
        """status != INACTIVE (cancel 복구 등) → 외부 리소스 보존, doc 만 즉시 청소.

        RDB hard_delete / 외부 cleanup / 알림 cascade 모두 skip — STALE_DOC 가드의 핵심.
        """
        user = UserFactory.create(user_id="USER_a", status=UserStatus.ACTIVE)
        user_repo_mock.find_by_id_for_update.return_value = user

        await service.purge(user_id="USER_a")

        user_repo_mock.hard_delete_by_id.assert_not_awaited()
        inbox_service_mock.cascade_user_withdrawn.assert_not_awaited()
        storage_mock.delete_by_prefix.assert_not_awaited()
        invalidate_cache_mock.assert_not_awaited()
        for stub in beanie_stubs.values():
            assert stub.find_call_count == 0
        # doc 만 청소
        withdrawal_request_repo_mock.delete_by_user_id.assert_awaited_once_with("USER_a")

    async def test_stale_doc_cleanup_failure_swallowed(
        self, service, user_repo_mock, withdrawal_request_repo_mock,
    ):
        """STALE_DOC doc 청소 실패해도 raise 없음 — 다음 사이클에서 재시도."""
        user = UserFactory.create(status=UserStatus.ACTIVE)
        user_repo_mock.find_by_id_for_update.return_value = user
        withdrawal_request_repo_mock.delete_by_user_id.side_effect = RuntimeError("mongo down")

        # raise 없이 정상 종료
        await service.purge(user_id=user.user_id)


# ──────────────────────────────────────────────────────────────────
# _purge_external — 단계별 best-effort + 알림 cascade
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestPurgeExternal:
    """Tests for WithdrawService._purge_external — 다단계 best-effort + 인박스 cascade.

    internal 메서드 직접 호출 — 단계 격리 검증. 한 단계 실패가 다음 단계로 전파되지 않음.
    """

    async def test_calls_all_beanie_documents(self, service, beanie_stubs):
        """5개 Mongo 컬렉션 모두 user_id 매칭으로 delete."""
        await service._purge_external(user_id="USER_a")

        for stub in beanie_stubs.values():
            assert stub.find_call_count == 1
            assert stub.last_filter == {"user_id": "USER_a"}

    async def test_calls_storage_delete_by_prefix(self, service, storage_mock):
        await service._purge_external(user_id="USER_a")

        storage_mock.delete_by_prefix.assert_awaited_once_with("USER_a")

    async def test_calls_redis_cache_invalidate(self, service, invalidate_cache_mock):
        await service._purge_external(user_id="USER_a")

        invalidate_cache_mock.assert_awaited_once_with("USER_a")

    async def test_calls_inbox_cascade(
        self, service, inbox_service_mock,
    ):
        """인박스 cascade — recipient/actor 매칭 항목 일괄 hard delete."""
        await service._purge_external(user_id="USER_a")

        inbox_service_mock.cascade_user_withdrawn.assert_awaited_once_with("USER_a")

    async def test_cleans_withdrawal_request_doc_at_end(
        self, service, withdrawal_request_repo_mock,
    ):
        """withdrawal_request doc 자체는 모든 정리 끝난 뒤 마지막에 청소."""
        await service._purge_external(user_id="USER_a")

        withdrawal_request_repo_mock.delete_by_user_id.assert_awaited_once_with("USER_a")

    async def test_mongo_failure_does_not_block_storage_or_inbox(
        self, service, beanie_stubs, storage_mock, inbox_service_mock,
    ):
        """Mongo 단계 실패해도 Storage / Inbox 단계 진행 — 단계 격리."""
        beanie_stubs["TripmateImage"].find = lambda _: _RaisingQuery()

        await service._purge_external(user_id="USER_a")

        storage_mock.delete_by_prefix.assert_awaited_once()
        inbox_service_mock.cascade_user_withdrawn.assert_awaited_once()

    async def test_storage_failure_does_not_block_inbox(
        self, service, storage_mock, inbox_service_mock,
    ):
        storage_mock.delete_by_prefix.side_effect = RuntimeError("s3 down")

        await service._purge_external(user_id="USER_a")

        inbox_service_mock.cascade_user_withdrawn.assert_awaited_once()

    async def test_doc_cleanup_failure_does_not_propagate(
        self, service, withdrawal_request_repo_mock,
    ):
        """마지막 단계 (doc 청소) 실패도 raise 없음 — 다음 worker tick 에서 재시도."""
        withdrawal_request_repo_mock.delete_by_user_id.side_effect = RuntimeError("mongo down")

        # raise 없이 정상 종료
        await service._purge_external(user_id="USER_a")


class _RaisingQuery:
    """`Document.find().delete()` chain 의 delete 단계에서 raise — Mongo 장애 시뮬레이션."""

    async def delete(self):
        raise RuntimeError("mongo down")
