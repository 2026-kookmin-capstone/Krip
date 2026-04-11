from typing import List

from app.database.session import UnitOfWork, transactional
from app.domain.tripmate.repository.tripmate_post_like import TripmatePostLikeRepository
from app.domain.tripmate.repository.tripmate_post import TripmatePostRepository
from app.domain.tripmate.model.tripmate_post_like import TripmatePostLike


class TripmatePostLikeService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow


    # ──────────────────── 좋아요 누른 유저 조회 ────────────────────

    @transactional
    async def get_liked_user_ids(self, post_id: str) -> List[str]:
        """
        게시글에 좋아요 누른 유저 ID 목록 조회

        1. 게시글 존재 검증
        2. 좋아요 누른 유저 ID 목록 반환 (최신순)
        """
        post_repo = TripmatePostRepository(self._session)
        like_repo = TripmatePostLikeRepository(self._session)

        post = await post_repo.find_by_id(post_id)
        if post is None:
            raise ValueError("존재하지 않는 게시글입니다.")

        return await like_repo.find_user_ids_by_post(post_id)


    # ──────────────────── 좋아요 추가 ────────────────────

    @transactional
    async def add_like(self, user_id: str, post_id: str) -> int:
        """
        게시글 좋아요 추가

        1. 게시글 존재 검증
        2. 이미 좋아요를 눌렀는지 확인 (중복 방지)
        3. 좋아요 저장 후 현재 좋아요 수 반환
        """
        post_repo = TripmatePostRepository(self._session)
        like_repo = TripmatePostLikeRepository(self._session)

        post = await post_repo.find_by_id(post_id)
        if post is None:
            raise ValueError("존재하지 않는 게시글입니다.")

        existing = await like_repo.find_by_user_and_post(user_id, post_id)
        if existing is not None:
            raise ValueError("이미 좋아요를 누른 게시글입니다.")

        like = TripmatePostLike(user_id=user_id, post_id=post_id)
        await like_repo.save(like)

        return await like_repo.count_by_post(post_id)


    # ──────────────────── 좋아요 삭제 ────────────────────

    @transactional
    async def remove_like(self, user_id: str, post_id: str) -> int:
        """
        게시글 좋아요 취소

        1. 좋아요 존재 검증
        2. 좋아요 삭제 후 현재 좋아요 수 반환
        """
        like_repo = TripmatePostLikeRepository(self._session)

        existing = await like_repo.find_by_user_and_post(user_id, post_id)
        if existing is None:
            raise ValueError("좋아요를 누르지 않은 게시글입니다.")

        await like_repo.delete_by_user_and_post(user_id, post_id)

        return await like_repo.count_by_post(post_id)
