from typing import Optional
from sqlalchemy import select, func, or_
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.tripmate.model.tripmate_post import TripmatePost
from app.domain.tripmate.model.tripmate_post_like import TripmatePostLike
from app.domain.auth.model.user_detail_inform import UserDetailInform


# 게시글 조회 개수
PAGE_SIZE = 30


class TripmatePostRepository:
    def __init__(self, session: AsyncSession):
        self.session = session


    # ──────────────────── Create ────────────────────

    async def save(self, post: TripmatePost) -> TripmatePost:
        self.session.add(post)
        await self.session.flush()
        return post


    # ──────────────────── Read (목록 — 커서 기반 페이지네이션) ────────────────────

    async def find_all_displayed(self, cursor: Optional[str] = None) -> list[TripmatePost]:
        """최신순 30개 조회, cursor(post_id) 이후부터 다음 페이지"""
        stmt = (
            select(
                TripmatePost,
                func.count(func.distinct(TripmatePostLike.user_id)).label("like_count"),
            )
            .outerjoin(TripmatePostLike, TripmatePost.post_id == TripmatePostLike.post_id)
            .options(joinedload(TripmatePost.images))
            .where(TripmatePost.is_displayed == True)
        )

        if cursor:
            # cursor로 받은 post_id의 created_at 기준으로 다음 페이지
            cursor_sub = select(TripmatePost.created_at).where(TripmatePost.post_id == cursor).scalar_subquery()
            stmt = stmt.where(
                or_(
                    TripmatePost.created_at < cursor_sub,
                    (TripmatePost.created_at == cursor_sub) & (TripmatePost.post_id < cursor),
                )
            )

        stmt = (
            stmt
            .group_by(TripmatePost.post_id)
            .order_by(TripmatePost.created_at.desc(), TripmatePost.post_id.desc())
            .limit(PAGE_SIZE)
        )

        result = await self.session.execute(stmt)
        rows = result.unique().all()
        return self._attach_like_counts(rows)


    # ──────────────────── Read (검색) ────────────────────

    async def search(
        self,
        keyword: str,
        cursor: Optional[str] = None,
    ) -> list[TripmatePost]:
        """제목, 내용, 작성자 닉네임으로 검색 (최신순, 커서 페이지네이션)"""
        like_pattern = f"%{keyword}%"

        stmt = (
            select(
                TripmatePost,
                func.count(func.distinct(TripmatePostLike.user_id)).label("like_count"),
            )
            .outerjoin(TripmatePostLike, TripmatePost.post_id == TripmatePostLike.post_id)
            .outerjoin(UserDetailInform, TripmatePost.user_id == UserDetailInform.user_id)
            .options(joinedload(TripmatePost.images))
            .where(
                TripmatePost.is_displayed == True,
                or_(
                    TripmatePost.title.ilike(like_pattern),
                    TripmatePost.content.ilike(like_pattern),
                    UserDetailInform.user_name.ilike(like_pattern),
                ),
            )
        )

        if cursor:
            cursor_sub = select(TripmatePost.created_at).where(TripmatePost.post_id == cursor).scalar_subquery()
            stmt = stmt.where(
                or_(
                    TripmatePost.created_at < cursor_sub,
                    (TripmatePost.created_at == cursor_sub) & (TripmatePost.post_id < cursor),
                )
            )

        stmt = (
            stmt
            .group_by(TripmatePost.post_id)
            .order_by(TripmatePost.created_at.desc(), TripmatePost.post_id.desc())
            .limit(PAGE_SIZE)
        )

        result = await self.session.execute(stmt)
        rows = result.unique().all()
        return self._attach_like_counts(rows)


    # ──────────────────── Update ────────────────────

    async def update(self, post: TripmatePost) -> TripmatePost:
        merged = await self.session.merge(post)
        await self.session.flush()
        return merged


    # ──────────────────── Delete ────────────────────

    async def delete(self, post: TripmatePost) -> None:
        await self.session.delete(post)


    # ──────────────────── 내부 유틸 ────────────────────

    @staticmethod
    def _attach_like_counts(rows) -> list[TripmatePost]:
        """쿼리 결과 Row에서 like_count를 Post 객체에 부착"""
        posts = []
        for row in rows:
            post = row[0]
            post.like_count = row[1]
            posts.append(post)
        return posts
