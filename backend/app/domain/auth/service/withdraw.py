from datetime import datetime, timedelta, timezone
from enum import Enum

from app.core.cache.key_category import KeyCategory
from app.core.cache.redis_cache import get_redis_cache_manager
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


def _registered_cache_key(user_id: str) -> str:
    return f"{KeyCategory.REGISTERED}:{user_id}"


class _PurgeOutcome(Enum):
    """worker 의 `_purge_rdb` 결과 — `purge` 가 후속 분기 결정에 사용."""
    DELETED = "deleted"        # status==INACTIVE → hard delete 완료 → 외부 정리 진행
    NO_USER = "no_user"        # RDB 에 user 없음 (이전 사이클 외부 정리 잔존) → 외부 정리 진행
    STALE_DOC = "stale_doc"    # status!=INACTIVE → cancel 복구 또는 dual-write 불일치 → doc 만 청소


async def invalidate_registered_cache(user_id: str) -> None:
    """`REGISTERED:{uid}` 캐시 무효화. 트랜잭션 commit **이후** 호출용 헬퍼.

    트랜잭션 내부에서 호출하면 commit 전에 캐시가 비워져 race 가 생긴다 — 동시 요청이
    아직 commit 되지 않은 ACTIVE 행을 읽고 캐시를 재기록 → 419 우회. 반드시 commit 후.
    """
    try:
        cache = get_redis_cache_manager()
        await cache.invalidate(_registered_cache_key(user_id))
    except Exception as e:
        # 실패해도 다음 캐시 TTL(24h) 만료 후 자연 정리 → 419 응답으로 자연 전환.
        logger.warning("REGISTERED 캐시 무효화 실패 (user_id={}): {}", user_id, e)


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

        캐시 무효화는 미커밋 ACTIVE 재캐시 race를 막기 위해 router가 commit 후 수행한다.
        """
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
            requested_at=now,
            scheduled_purge_at=purge_at,
        )

        logger.info(
            "탈퇴 요청 접수 (user_id={}, purge_at={})", user_id, purge_at.isoformat(),
        )
        return purge_at

    async def revoke_user_chat_state(self, user_id: str) -> None:
        """commit 후 활성 chat session을 즉시 revoke한다."""
        await self._chat_purge.revoke_all_sessions(user_id)

    async def purge(self, user_id: str) -> None:
        """RDB 삭제 후 Mongo, Object Storage, Redis를 best-effort로 정리한다.

        `_purge_rdb`와 cancel은 같은 row lock을 경쟁한다. cancel이 이기면 STALE_DOC만
        제거하고 외부 데이터는 보존한다. 외부 정리 실패 시 purge doc을 남겨 재시도한다.
        """
        outcome = await self._purge_rdb(user_id)

        if outcome == _PurgeOutcome.STALE_DOC:
            logger.warning(
                "탈퇴 영구 삭제 — RDB status 가 INACTIVE 아님 (cancel 복구 또는 "
                "dual-write 잔존), 외부 리소스 보존 + stale doc 만 정리 (user_id={})",
                user_id,
            )
            try:
                await self.withdrawal_request_repo.delete_by_user_id(user_id)
            except Exception as e:
                # 다음 사이클에서 같은 가드에 다시 걸려 재시도.
                logger.error(
                    "탈퇴 영구 삭제 — stale doc 정리 실패, 다음 tick 재시도 (user_id={}): {}",
                    user_id, e,
                )
            return

        await self._purge_external(user_id)

    @transactional
    async def _purge_rdb(self, user_id: str) -> "_PurgeOutcome":
        """row lock 안에서 status를 검사하고 조건부 hard delete한다."""
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
        await self._set_active(user_id)

        try:
            await self.withdrawal_request_repo.delete_by_user_id(user_id)
        except Exception as e:
            logger.warning(
                "탈퇴 취소 — Mongo doc 정리 실패 (status 는 이미 ACTIVE), "
                "worker STALE_DOC 가드가 다음 사이클에서 정리 예정 (user_id={}): {}",
                user_id, e,
            )

        logger.info("탈퇴 요청 취소 (user_id={})", user_id)

    @transactional
    async def _set_active(self, user_id: str) -> None:
        """row lock 안에서 RDB status만 ACTIVE로 복구한다."""
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

    async def _purge_external(self, user_id: str) -> None:
        """MongoDB / Object Storage / Redis 정리. 단계별 best-effort."""
        # MongoDB (유저 데이터)
        try:
            await TripmateImage.find({"user_id": user_id}).delete()
            await TripmatePostDraft.find({"user_id": user_id}).delete()
            await TripmateSearchHistory.find({"user_id": user_id}).delete()
            await TourSearchHistory.find({"user_id": user_id}).delete()
            await FriendSearchHistory.find({"user_id": user_id}).delete()
            logger.info("탈퇴 영구 삭제 — MongoDB 유저 데이터 삭제 완료 (user_id={})", user_id)
        except Exception as e:
            logger.error(
                "탈퇴 영구 삭제 — MongoDB 삭제 실패, orphan 정리 필요 (user_id={}): {}",
                user_id, e,
            )

        # 인박스 cascade (recipient/actor 양쪽 매칭) — InboxService 가 self-swallow.
        # 다음 worker 사이클에서 STALE_DOC 가드가 이미 RDB 상으론 사라진 user 의 doc 만 청소
        # 하므로, 인박스 cascade 가 실패해도 stale 항목은 TTL 30일로 자연 정리되어 안전.
        await self.inbox_service.cascade_user_withdrawn(user_id)

        # Object Storage
        try:
            await self.storage.delete_by_prefix(user_id)
            logger.info("탈퇴 영구 삭제 — Object Storage 삭제 완료 (user_id={})", user_id)
        except Exception as e:
            logger.error(
                "탈퇴 영구 삭제 — Object Storage 삭제 실패, orphan 파일 정리 필요 (user_id={}): {}",
                user_id, e,
            )

        # Redis (REGISTERED 플래그 — 요청 시점에 이미 무효화되었지만 30일 사이 재로그인
        # 등으로 다시 채워졌을 가능성에 대한 방어. TTL(24h) 보다 길게 살아있을 일은 없으나
        # 보수적으로 한 번 더 정리.)
        await invalidate_registered_cache(user_id)

        # chat 도메인 데이터성 키 (unread:{user_id} 등) — TTL 없어 명시 정리 필요.
        # 도메인 경계 유지를 위해 chat 의 cleanup 훅 통해 호출.
        await self._chat_purge.cleanup_user_data(user_id)

        # withdrawal_request 자체 — 모든 정리 끝난 뒤 마지막에 제거
        try:
            await self.withdrawal_request_repo.delete_by_user_id(user_id)
        except Exception as e:
            # 이게 실패하면 다음 스케줄러 tick 에서 같은 doc 가 다시 잡혀 purge 가 재실행됨.
            # _purge_rdb 는 idempotent (user 없으면 통과), _purge_external 도 멱등 → 재실행 안전.
            logger.error(
                "탈퇴 영구 삭제 — withdrawal_request doc 삭제 실패, 다음 tick 에서 재시도 (user_id={}): {}",
                user_id, e,
            )
