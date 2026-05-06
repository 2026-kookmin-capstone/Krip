"""FeedPostLike 리포지토리 — composite PK `(user_id, post_id)`.

`tripmate_post_like` 패턴 그대로:
    - `find_by_user_and_post` : 단건 조회 (composite PK lookup)
    - `count_by_post`         : 좋아요 수 (인덱스 prefix=post_id)
    - `find_user_ids_by_post` : 누른 유저 목록 (최신순)
    - `delete_by_user_and_post`: 단건 삭제

`delete_by_user_id` / `delete_by_post_id` 는 두지 않음 — 양쪽 FK ON DELETE CASCADE 가
유저 탈퇴 / 게시물 삭제 시 자동 정리.
"""
from typing import Optional
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.feed.model.feed_post_like import FeedPostLike


class FeedPostLikeRepository:
    def __init__(self, session: AsyncSession):
        self.session = session


    # ──────────────────── Create ────────────────────

    async def save(self, like: FeedPostLike) -> FeedPostLike:
        """좋아요 INSERT — composite PK 충돌 시 IntegrityError 그대로 propagate."""
        self.session.add(like)
        await self.session.flush()
        return like


    # ──────────────────── Read ────────────────────

    async def find_by_user_and_post(
        self, user_id: str, post_id: str,
    ) -> Optional[FeedPostLike]:
        """특정 유저의 특정 게시물 좋아요 단건 조회 — composite PK lookup."""
        return await self.session.get(FeedPostLike, (user_id, post_id))


    async def count_by_post(self, post_id: str) -> int:
        """게시물의 좋아요 수 — `ix_feed_post_like_post_id` prefix-scan."""
        stmt = select(func.count()).where(FeedPostLike.post_id == post_id)
        result = await self.session.execute(stmt)
        return result.scalar_one()


    async def find_user_ids_by_post(self, post_id: str) -> list[str]:
        """게시물에 좋아요 누른 유저 ID 목록 (최신순). MVP 는 페이지네이션 없이 일괄 반환."""
        stmt = (
            select(FeedPostLike.user_id)
            .where(FeedPostLike.post_id == post_id)
            .order_by(FeedPostLike.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


    # ──────────────────── Delete ────────────────────

    async def delete_by_user_and_post(self, user_id: str, post_id: str) -> None:
        """단건 삭제 — bulk delete statement (load 없이 직접 DELETE)."""
        stmt = delete(FeedPostLike).where(
            FeedPostLike.user_id == user_id,
            FeedPostLike.post_id == post_id,
        )
        await self.session.execute(stmt)
