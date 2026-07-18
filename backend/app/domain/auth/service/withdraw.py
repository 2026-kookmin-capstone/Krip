from datetime import datetime, timedelta, timezone
from enum import Enum
from uuid import uuid4

from sqlalchemy import text

from app.core.logger import get_logger
from app.core.object_storage import get_object_storage
from app.database.session import UnitOfWork, transactional
from app.domain.auth.model.user import UserStatus
from app.domain.auth.model.withdrawal_request import WITHDRAWAL_GRACE_PERIOD_DAYS
from app.domain.auth.repository.user import UserRepository
from app.domain.auth.repository.withdrawal_request import WithdrawalRequestRepository
from app.domain.auth.service.exception import (
    WithdrawalAlreadyRequestedError,
    WithdrawalNotPendingError,
)
from app.domain.friend.model.search_history import FriendSearchHistory
from app.domain.notification.service.inbox import InboxService
from app.domain.tour.model.tour_search_history import TourSearchHistory
from app.domain.tripmate.model.tripmate_image import TripmateImage
from app.domain.tripmate.model.tripmate_post_draft import TripmatePostDraft
from app.domain.tripmate.model.tripmate_search_history import TripmateSearchHistory


logger = get_logger("auth.withdraw")


class _PurgeOutcome(Enum):
    """worker 의 `_purge_rdb` 결과 — `purge` 가 후속 분기 결정에 사용."""
    DELETED = "deleted"        # status==INACTIVE → hard delete 완료 → 외부 정리 진행
    NO_USER = "no_user"        # RDB 에 user 없음 (이전 사이클 외부 정리 잔존) → 외부 정리 진행
    STALE_DOC = "stale_doc"    # status!=INACTIVE → cancel 복구 또는 dual-write 불일치 → doc 만 청소
    STALE_GENERATION = "stale_generation"  # worker snapshot 뒤 cancel/re-withdraw → 전부 보존


class WithdrawService:
    """회원 탈퇴 — 30일 유예 정책.

    INACTIVE 사용자는 middleware가 보호 경로를 차단한다. 재로그인 후 cancel endpoint만
    허용하며, 만료 요청은 worker가 RDB와 외부 리소스를 정리한다.
    """

    def __init__(self, uow: UnitOfWork, inbox_service: InboxService, user_purge_cache_service):
        # user_purge_cache_service 는 chat 도메인 서비스 — type hint 생략으로 순환 import 회피
        # (cross-domain anti-corruption layer).
        self.uow = uow
        self.inbox_service = inbox_service
        self.storage = get_object_storage()
        self.withdrawal_request_repo = WithdrawalRequestRepository()
        self._chat_purge = user_purge_cache_service

    @transactional
    async def request_withdraw(self, user_id: str) -> datetime:
        """INACTIVE 전환과 Mongo purge 요청을 함께 수행한다.

        chat session revoke는 router가 commit 후 수행한다.
        """
        await self._lock_withdrawal(user_id)
        user_repo = UserRepository(self._session)

        user = await user_repo.find_by_id(user_id)
        if user is None:
            raise ValueError("존재하지 않는 유저입니다.")
        if user.status == UserStatus.INACTIVE:
            raise WithdrawalAlreadyRequestedError("이미 탈퇴가 요청된 유저입니다.")

        user.status = UserStatus.INACTIVE
        await user_repo.update(user)

        now = datetime.now(timezone.utc)
        purge_at = now + timedelta(days=WITHDRAWAL_GRACE_PERIOD_DAYS)

        # RDB-MongoDB strict atomicity 는 없지만, status=ACTIVE 가드(위) 가 통과한
        # 시점부터는 사실상 단일 호출자 → upsert 로 충분.
        await self.withdrawal_request_repo.upsert(
            user_id=user_id,
            generation_id=uuid4().hex,
            requested_at=now,
            scheduled_purge_at=purge_at,
        )

        logger.info(
            "탈퇴 요청 접수 (user_id={}, purge_at={})", user_id, purge_at.isoformat(),
        )
        return purge_at

    @transactional
    async def revoke_user_chat_state(self, user_id: str) -> None:
        """현재 탈퇴 세대가 유효한 동안만 chat session을 revoke한다."""
        await self._lock_withdrawal(user_id)
        user = await UserRepository(self._session).find_by_id_for_update(user_id)
        if user is None or user.status != UserStatus.INACTIVE:
            return
        await self._chat_purge.revoke_all_sessions(user_id)

    async def purge(
        self,
        user_id: str,
        expected_generation_id: str | None = None,
        expected_requested_at: datetime | None = None,
    ) -> None:
        """RDB 삭제 후 Mongo, Object Storage, Redis를 best-effort로 정리한다.

        `_purge_rdb`와 cancel은 같은 row lock을 경쟁한다. cancel이 이기면 STALE_DOC만
        제거하고 외부 데이터는 보존한다. 외부 정리 실패 시 purge doc을 남겨 재시도한다.
        """
        outcome = await self._purge_rdb(
            user_id,
            expected_generation_id,
            expected_requested_at,
        )

        if outcome == _PurgeOutcome.STALE_GENERATION:
            logger.info(
                "탈퇴 영구 삭제 — worker 세대가 현재 요청과 달라 전체 보존 (user_id={})",
                user_id,
            )
            return

        if outcome == _PurgeOutcome.STALE_DOC:
            logger.warning(
                "탈퇴 영구 삭제 — RDB status 가 INACTIVE 아님 (cancel 복구 또는 "
                "dual-write 잔존), 외부 리소스 보존 + stale doc 만 정리 (user_id={})",
                user_id,
            )
            await self._delete_retry_marker(
                user_id,
                expected_generation_id,
                expected_requested_at,
            )
            return

        await self._purge_external(
            user_id,
            expected_generation_id,
            expected_requested_at,
        )

    @transactional
    async def _purge_rdb(
        self,
        user_id: str,
        expected_generation_id: str | None = None,
        expected_requested_at: datetime | None = None,
    ) -> "_PurgeOutcome":
        """generation fence와 row lock 안에서 조건부 hard delete한다."""
        await self._lock_withdrawal(user_id)
        if expected_requested_at is not None:
            marker = await self.withdrawal_request_repo.find_by_user_id(user_id)
            if marker is None or not self._is_expected_generation(
                marker,
                expected_generation_id,
                expected_requested_at,
            ):
                return _PurgeOutcome.STALE_GENERATION

        user_repo = UserRepository(self._session)
        user = await user_repo.find_by_id_for_update(user_id)

        if user is None:
            logger.info(
                "탈퇴 영구 삭제 — RDB 에 user 없음, 외부 리소스 정리만 진행 (user_id={})",
                user_id,
            )
            return _PurgeOutcome.NO_USER

        if user.status != UserStatus.INACTIVE:
            return _PurgeOutcome.STALE_DOC

        await user_repo.hard_delete_by_id(user_id)
        logger.info("탈퇴 영구 삭제 — RDB 삭제 완료 (user_id={})", user_id)
        return _PurgeOutcome.DELETED

    async def cancel_withdraw(self, user_id: str) -> None:
        """row lock으로 INACTIVE를 ACTIVE로 복구한 뒤 Mongo purge doc을 제거한다.

        Mongo 삭제는 RDB commit 후 수행한다. 실패해도 worker의 STALE_DOC 가드가 다음
        사이클에 정리하므로 INACTIVE 상태에서 purge doc만 사라지는 stuck 상태를 피한다.
        """
        marker = await self.withdrawal_request_repo.find_by_user_id(user_id)
        await self._set_active(user_id)

        try:
            if marker is not None:
                await self.withdrawal_request_repo.delete_if_generation(
                    user_id,
                    marker.generation_id,
                    marker.requested_at,
                )
        except Exception as e:
            logger.warning(
                "탈퇴 취소 — Mongo doc 정리 실패 (status 는 이미 ACTIVE), "
                "worker STALE_DOC 가드가 다음 사이클에서 정리 예정 (user_id={}): {}",
                user_id, e,
            )

        logger.info("탈퇴 요청 취소 (user_id={})", user_id)

    @transactional
    async def _set_active(self, user_id: str) -> None:
        """withdrawal fence와 row lock 안에서 RDB status를 ACTIVE로 복구한다."""
        await self._lock_withdrawal(user_id)
        user_repo = UserRepository(self._session)
        user = await user_repo.find_by_id_for_update(user_id)
        if user is None:
            raise ValueError("존재하지 않는 유저입니다.")
        if user.status != UserStatus.INACTIVE:
            raise WithdrawalNotPendingError(
                f"탈퇴 요청 중인 유저가 아닙니다 (현재 status={user.status.value}).",
            )
        user.status = UserStatus.ACTIVE
        await user_repo.update(user)

    async def _lock_withdrawal(self, user_id: str) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_name, 0))"),
            {"lock_name": f"withdrawal:{user_id}"},
        )

    async def _purge_external(
        self,
        user_id: str,
        expected_generation_id: str | None = None,
        expected_requested_at: datetime | None = None,
    ) -> None:
        """외부 저장소를 끝까지 정리하고 필수 단계가 모두 성공한 경우에만 retry doc을 제거한다."""
        failed_stages: list[str] = []

        # MongoDB (유저 데이터)
        mongo_documents = (
            ("tripmate_image", TripmateImage),
            ("tripmate_post_draft", TripmatePostDraft),
            ("tripmate_search_history", TripmateSearchHistory),
            ("tour_search_history", TourSearchHistory),
            ("friend_search_history", FriendSearchHistory),
        )
        for stage, document in mongo_documents:
            try:
                await document.find({"user_id": user_id}).delete()
            except Exception as e:
                failed_stages.append(stage)
                logger.error(
                    "탈퇴 영구 삭제 — MongoDB {} 삭제 실패, 다음 tick 재시도 "
                    "(user_id={}): {}",
                    stage,
                    user_id,
                    e,
                )
        if not any(stage in failed_stages for stage, _ in mongo_documents):
            logger.info("탈퇴 영구 삭제 — MongoDB 유저 데이터 삭제 완료 (user_id={})", user_id)

        # 인박스 cascade (recipient/actor 양쪽 매칭) — InboxService 가 self-swallow.
        # 다음 worker 사이클에서 STALE_DOC 가드가 이미 RDB 상으론 사라진 user 의 doc 만 청소
        # 하므로, 인박스 cascade 가 실패해도 stale 항목은 TTL 30일로 자연 정리되어 안전.
        await self.inbox_service.cascade_user_withdrawn(user_id)

        # Object Storage
        try:
            await self.storage.delete_by_prefix(user_id)
            logger.info("탈퇴 영구 삭제 — Object Storage 삭제 완료 (user_id={})", user_id)
        except Exception as e:
            failed_stages.append("object_storage")
            logger.error(
                "탈퇴 영구 삭제 — Object Storage 삭제 실패, 다음 tick 재시도 (user_id={}): {}",
                user_id, e,
            )

        # chat 도메인 데이터성 키 (unread:{user_id} 등) — TTL 없어 명시 정리 필요.
        # 도메인 경계 유지를 위해 chat 의 cleanup 훅 통해 호출.
        try:
            chat_cleanup_ok = await self._chat_purge.cleanup_user_data(user_id)
            if chat_cleanup_ok is False:
                failed_stages.append("chat_redis")
        except Exception as e:
            failed_stages.append("chat_redis")
            logger.error(
                "탈퇴 영구 삭제 — chat Redis 정리 실패, 다음 tick 재시도 (user_id={}): {}",
                user_id,
                e,
            )

        if failed_stages:
            raise RuntimeError(f"외부 정리 미완료: {', '.join(failed_stages)}")

        await self._delete_retry_marker(
            user_id,
            expected_generation_id,
            expected_requested_at,
        )

    async def _delete_retry_marker(
        self,
        user_id: str,
        expected_generation_id: str | None,
        expected_requested_at: datetime | None,
    ) -> None:
        if expected_requested_at is None:
            await self.withdrawal_request_repo.delete_by_user_id(user_id)
            return
        await self.withdrawal_request_repo.delete_if_generation(
            user_id,
            expected_generation_id,
            expected_requested_at,
        )

    @staticmethod
    def _is_expected_generation(marker, generation_id, requested_at: datetime) -> bool:
        if generation_id is not None:
            return marker.generation_id == generation_id
        return marker.generation_id is None and marker.requested_at == requested_at
