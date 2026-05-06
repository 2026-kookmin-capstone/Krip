"""FeedPostComment 리포지토리 — `(post_id, created_at)` 컴파운드 인덱스 활용.

쿼리 전략:
    - 단일 인덱스 `ix_feed_post_comment_post_created` 가 게시물별 시간순 조회 / 페이지네이션
      / count 모두 커버.
    - 정렬은 DESC (최신순) — 피드 list 와 일관. 인덱스 reverse-scan.
    - 커서 페이지네이션은 friend / feed_post 패턴 그대로 `(created_at, comment_id)` 튜플 비교.
    - delete cascade 는 `users` / `feed_post` FK ON DELETE CASCADE 가 처리 — 본 리포지토리는
      단건 삭제만.
"""
from typing import Optional
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.feed.model.feed_post_comment import FeedPostComment


# 댓글 페이지 크기 — 모바일 한 화면에 fit. 피드 list 와 다른 값 (댓글은 더 짧고 많이 쌓임).
PAGE_SIZE = 20


class FeedPostCommentRepository:
    def __init__(self, session: AsyncSession):
        self.session = session


    # ──────────────────── Create ────────────────────

    async def save(self, comment: FeedPostComment) -> FeedPostComment:
        """댓글 INSERT — comment_id PK / CHECK(content) 위반은 그대로 propagate."""
        self.session.add(comment)
        await self.session.flush()
        return comment


    # ──────────────────── Read (단건) ────────────────────

    async def find_by_id(self, comment_id: str) -> Optional[FeedPostComment]:
        """comment_id PK 단건 — 권한 검증 / 단일 조회용."""
        return await self.session.get(FeedPostComment, comment_id)


    async def count_by_post(self, post_id: str) -> int:
        """게시물 댓글 수 — 인덱스 prefix=post_id 로 효율적."""
        stmt = select(func.count()).where(FeedPostComment.post_id == post_id)
        result = await self.session.execute(stmt)
        return result.scalar_one()


    # ──────────────────── Read (목록 — 커서 페이지네이션) ────────────────────

    async def find_by_post(
        self,
        *,
        post_id: str,
        cursor: Optional[str] = None,
    ) -> list[FeedPostComment]:
        """게시물 댓글 목록 — 최신순 PAGE_SIZE 만큼.

        정렬: `(created_at DESC, comment_id DESC)` — 인덱스 reverse-scan.
        cursor 는 마지막 row 의 `comment_id` — `feed_post.find_by_owner` 와 동일 패턴
        (scalar_subquery 로 created_at 인라인 lookup + 튜플 비교).
        """
        stmt = select(FeedPostComment).where(FeedPostComment.post_id == post_id)

        if cursor is not None:
            cursor_sub = (
                select(FeedPostComment.created_at)
                .where(FeedPostComment.comment_id == cursor)
                .scalar_subquery()
            )
            stmt = stmt.where(
                or_(
                    FeedPostComment.created_at < cursor_sub,
                    (FeedPostComment.created_at == cursor_sub)
                    & (FeedPostComment.comment_id < cursor),
                )
            )

        stmt = (
            stmt.order_by(
                FeedPostComment.created_at.desc(),
                FeedPostComment.comment_id.desc(),
            )
            .limit(PAGE_SIZE)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


    # ──────────────────── Delete ────────────────────

    async def delete(self, comment: FeedPostComment) -> None:
        """단건 삭제 — service 가 작성자 검증 후 호출."""
        await self.session.delete(comment)
