from app.domain.auth.repository.user_repository import UserRepository
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

        삭제 순서:
            1. Object Storage: 유저 업로드 파일 전체 삭제
            2. MongoDB: tripmate_image, tripmate_post_draft,
                        tripmate_search_history, tour_search_history
            3. RDB (CASCADE): user → user_detail_inform, user_travel_style,
                        tripmate_post (→ tripmate_post_image, tripmate_post_like),
                        tripmate_post_like, favorite_place
            4. Redis: 2차 회원가입 캐시 삭제
        """
        user_repo = UserRepository(self._session)

        user = await user_repo.find_by_id(user_id)
        if user is None:
            raise ValueError("존재하지 않는 유저입니다.")

        # 1) Object Storage — 유저 폴더 하위 파일 전체 삭제
        await self.storage.delete_by_prefix(user_id)
        logger.info("Object Storage 삭제 완료 (user_id={})", user_id)

        # 2) MongoDB — 유저 관련 도큐먼트 전체 삭제
        await TripmateImage.find({"user_id": user_id}).delete()
        await TripmatePostDraft.find({"user_id": user_id}).delete()
        await TripmateSearchHistory.find({"user_id": user_id}).delete()
        await TourSearchHistory.find({"user_id": user_id}).delete()
        logger.info("MongoDB 삭제 완료 (user_id={})", user_id)

        # 3) RDB — User 삭제 (DB CASCADE로 연관 테이블 전체 삭제)
        deleted = await user_repo.hard_delete_by_id(user_id)
        if not deleted:
            raise ValueError("유저 삭제에 실패했습니다.")
        logger.info("RDB 삭제 완료 (user_id={})", user_id)

        # 4) Redis — 2차 회원가입 캐시 삭제
        cache = get_redis_cache_manager()
        await cache.invalidate(f"{KeyCategory.REGISTERED}:{user_id}")
        logger.info("Redis 캐시 삭제 완료 (user_id={})", user_id)
