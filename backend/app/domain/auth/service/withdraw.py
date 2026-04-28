from app.domain.auth.repository.user import UserRepository
from app.domain.tripmate.model.tripmate_image import TripmateImage
from app.domain.tripmate.model.tripmate_post_draft import TripmatePostDraft
from app.domain.tripmate.model.tripmate_search_history import TripmateSearchHistory
from app.domain.tour.model.tour_search_history import TourSearchHistory
from app.database.session import UnitOfWork, transactional
from app.core.object_storage import get_object_storage
from app.core.cache.redis_cache import get_redis_cache_manager
from app.core.cache.key_category import KeyCategory
from app.core.logger import get_logger


logger = get_logger("auth.withdraw")


class WithdrawService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow
        self.storage = get_object_storage()

    @transactional
    async def withdraw(self, user_id: str) -> None:
        """유저 하드 탈퇴 — 유저와 관련된 모든 데이터 영구 삭제

        삭제 순서 (RDB 먼저 → 외부 리소스 best-effort):
            1. RDB (CASCADE): user →
                - user_detail_inform, user_travel_style
                - tripmate_post (→ tripmate_post_image, tripmate_post_like)
                - tripmate_post_like (좋아요 누른 입장)
                - favorite_place
                - friendship (requester/addressee 양측)
                - user_block (blocker/blocked 양측)
            2. MongoDB: tripmate_image, tripmate_post_draft,
                        tripmate_search_history, tour_search_history
            3. Object Storage: uploads/perm/{user_id}/* 전체 삭제
            4. Redis: 2차 회원가입 캐시 삭제

        외부 리소스(2~4)는 개별 try/except 로 격리한다.
        한 단계가 실패해도 다음 단계는 계속 진행하며, 실패는 로그로만 남겨
        orphan 데이터가 남을 수 있으나 유저 참조 경로(RDB) 는 이미 끊겨 있어
        사용자 경험에는 영향이 없다. RDB 는 원자적으로 확정 → 유저는 확실히 삭제.
        """
        user_repo = UserRepository(self._session)

        user = await user_repo.find_by_id(user_id)
        if user is None:
            raise ValueError("존재하지 않는 유저입니다.")

        # 1) RDB — User 삭제 (DB CASCADE). 실패 시 @transactional 이 rollback 해
        #    외부 리소스는 전혀 손대지 않은 상태로 재시도 가능.
        deleted = await user_repo.hard_delete_by_id(user_id)
        if not deleted:
            raise ValueError("유저 삭제에 실패했습니다.")
        logger.info("RDB 삭제 완료 (user_id={})", user_id)

        # 2) MongoDB — best-effort. 실패해도 유저 삭제는 확정된 상태 유지.
        try:
            await TripmateImage.find({"user_id": user_id}).delete()
            await TripmatePostDraft.find({"user_id": user_id}).delete()
            await TripmateSearchHistory.find({"user_id": user_id}).delete()
            await TourSearchHistory.find({"user_id": user_id}).delete()
            logger.info("MongoDB 삭제 완료 (user_id={})", user_id)
        except Exception as e:
            logger.error("MongoDB 삭제 실패 — orphan 데이터 정리 필요 (user_id={}): {}", user_id, e)

        # 3) Object Storage — best-effort
        try:
            await self.storage.delete_by_prefix(user_id)
            logger.info("Object Storage 삭제 완료 (user_id={})", user_id)
        except Exception as e:
            logger.error("Object Storage 삭제 실패 — orphan 파일 정리 필요 (user_id={}): {}", user_id, e)

        # 4) Redis — best-effort
        try:
            cache = get_redis_cache_manager()
            await cache.invalidate(f"{KeyCategory.REGISTERED}:{user_id}")
            logger.info("Redis 캐시 삭제 완료 (user_id={})", user_id)
        except Exception as e:
            logger.error("Redis 캐시 삭제 실패 (user_id={}): {}", user_id, e)
