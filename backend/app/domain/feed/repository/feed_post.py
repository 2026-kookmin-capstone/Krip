"""FeedPost 리포지토리.

좋아요/댓글 수 / viewer 좋아요 여부는 correlated subquery 로 단일 SELECT 합성 (N+1 회피).
visibility 분기는 service 가 결정 — 본 리포지토리는 visibility 정책을 모름.
"""
from typing import Optional

from sqlalchemy import exists, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.feed.dto.feed_post import FeedPostWithCounts
from app.domain.feed.model.feed_post import FeedPost, FeedVisibility
from app.domain.feed.model.feed_post_comment import FeedPostComment
from app.domain.feed.model.feed_post_like import FeedPostLike
from app.util.cursor import decode_cursor, keyset_where


# 그리드 3열 × 10행.
PAGE_SIZE = 30


def _like_count_subquery():
    return (
        select(func.count())
        .select_from(FeedPostLike)
        .where(FeedPostLike.post_id == FeedPost.post_id)
        .correlate(FeedPost)
        .scalar_subquery()
    )


def _comment_count_subquery():
    return (
        select(func.count())
        .select_from(FeedPostComment)
        .where(FeedPostComment.post_id == FeedPost.post_id)
        .correlate(FeedPost)
        .scalar_subquery()
    )


def _is_liked_subquery(viewer_id: Optional[str]):
    """viewer 의 좋아요 여부 — `viewer_id=None` 이면 SQL 측 false 단락 평가.

    EXISTS lookup 이 composite PK `(user_id, post_id)` 로 0/1 건 평가 후 즉시 종료.
    """
    if viewer_id is None:
        return literal(False).label("is_liked")
    return exists(
        select(1)
        .select_from(FeedPostLike)
        .where(
            FeedPostLike.post_id == FeedPost.post_id,
            FeedPostLike.user_id == viewer_id,
        )
        .correlate(FeedPost)
    ).label("is_liked")


class FeedPostRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, post: FeedPost) -> FeedPost:
        self.session.add(post)
        await self.session.flush()
        return post

    async def update(self, post: FeedPost) -> FeedPost:
        """변경 필드 flush — 호출측이 attached post 필드를 직접 mutate 후 호출."""
        await self.session.flush()
        return post

    async def find_by_post_id(
        self,
        post_id: str,
        viewer_id: Optional[str] = None,
    ) -> Optional[FeedPostWithCounts]:
        """PK 단건 + 카운트 + viewer 좋아요 여부 일괄 조회.

        access check 경로는 카운트 미사용 (~0.5ms) 이지만 메서드 분화 회피 — 단일 진입점 우선.
        """
        like_count = _like_count_subquery()
        comment_count = _comment_count_subquery()
        is_liked = _is_liked_subquery(viewer_id)
        stmt = (
            select(
                FeedPost,
                like_count.label("like_count"),
                comment_count.label("comment_count"),
                is_liked,
            )
            .where(FeedPost.post_id == post_id)
        )
        result = await self.session.execute(stmt)
        row = result.one_or_none()
        if row is None:
            return None
        return FeedPostWithCounts(
            post=row.FeedPost,
            like_count=row.like_count,
            comment_count=row.comment_count,
            is_liked=bool(row.is_liked),
        )

    async def find_by_owner(
        self,
        *,
        owner_id: str,
        visibilities: list[FeedVisibility],
        cursor: Optional[str] = None,
        limit: int = PAGE_SIZE,
        viewer_id: Optional[str] = None,
    ) -> list[FeedPostWithCounts]:
        """owner + visibility IN-list 로 커서 페이지네이션 + 카운트 합성.

        `(created_at DESC, post_id DESC)` — 컴파운드 인덱스 reverse-scan.
        cursor 는 (created_at, post_id) 를 담은 opaque 토큰 — keyset_where 로 튜플 비교.
        `limit` 은 popup 등 고정 N 케이스를 위해 override 가능.
        """
        if not visibilities:
            return []

        like_count = _like_count_subquery()
        comment_count = _comment_count_subquery()
        is_liked = _is_liked_subquery(viewer_id)
        stmt = select(
            FeedPost,
            like_count.label("like_count"),
            comment_count.label("comment_count"),
            is_liked,
        ).where(
            FeedPost.user_id == owner_id,
            FeedPost.visibility.in_(visibilities),
        )

        if cursor is not None:
            decoded = decode_cursor(cursor)
            if decoded is None:
                raise ValueError("유효하지 않은 커서입니다.")
            cur_ts, cur_id = decoded
            stmt = stmt.where(keyset_where(
                FeedPost.created_at, FeedPost.post_id, cur_ts, cur_id,
            ))

        stmt = (
            stmt.order_by(FeedPost.created_at.desc(), FeedPost.post_id.desc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return [
            FeedPostWithCounts(
                post=row.FeedPost,
                like_count=row.like_count,
                comment_count=row.comment_count,
                is_liked=bool(row.is_liked),
            )
            for row in result.all()
        ]

    async def delete(self, post: FeedPost) -> None:
        """단건 삭제. like/comment 는 ORM cascade + FK CASCADE 로 자동 정리."""
        await self.session.delete(post)
