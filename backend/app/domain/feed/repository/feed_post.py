"""FeedPost 리포지토리

쿼리 전략:
    - 단일 컴파운드 인덱스 `(user_id, visibility, created_at, post_id)` 가 모든 조회 +
      페이지네이션 + count 를 커버 (모델 docstring 참조).
    - viewer 관계 (본인 / 친구 / 비친구 / 차단) 분기는 모두 service 가 결정해
      `visibilities` 부분집합으로 전달 — 본 리포지토리는 visibility 정책을 모름.
    - 커서 페이지네이션은 friend 도메인의 (`updated_at`, `friendship_id`) 튜플 비교 패턴을
      (`created_at`, `post_id`) 로 옮긴 것과 동일.
    - `delete_by_user_id` 는 두지 않음 — `users` FK ON DELETE CASCADE 가 자동 정리.
"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_

from app.domain.feed.model.feed_post import FeedPost, FeedVisibility


# 피드 그리드 3열 × 10행. friend 도메인 PAGE_SIZE 와 동일.
PAGE_SIZE = 30


class FeedPostRepository:
    def __init__(self, session: AsyncSession):
        self.session = session


    # ──────────────────── Create / Update ────────────────────

    async def save(self, post: FeedPost) -> FeedPost:
        """새 게시물 INSERT — post_id PK 충돌 시 IntegrityError 그대로 propagate."""
        self.session.add(post)
        await self.session.flush()
        return post


    async def update(self, post: FeedPost) -> FeedPost:
        """변경된 필드 flush — visibility / caption 변경 경로 전용.

        호출 측에서 attached post 의 필드를 직접 mutate 한 뒤 본 메서드를 호출한다
        (friend 도메인의 `FriendshipRepository.update` 와 동일 패턴).
        """
        await self.session.flush()
        return post


    # ──────────────────── Read (단건) ────────────────────

    async def find_by_post_id(self, post_id: str) -> Optional[FeedPost]:
        """post_id PK 단건 조회 — 권한 검증 / 단일 조회용."""
        return await self.session.get(FeedPost, post_id)


    # ──────────────────── Read (목록 — 커서 페이지네이션) ────────────────────

    async def find_by_owner(
        self,
        *,
        owner_id: str,
        visibilities: list[FeedVisibility],
        cursor: Optional[str] = None,
    ) -> list[FeedPost]:
        """소유자 + visibility 부분집합 조건으로 PAGE_SIZE 만큼 조회.

        viewer 관계에 따라 service 가 `visibilities` 를 결정한다:
            - 본인     → [PRIVATE, FRIENDS, PUBLIC]
            - 친구     → [FRIENDS, PUBLIC]
            - 비친구   → [PUBLIC]
            - 차단 관계 → service 가 호출 자체를 막음 (본 메서드에는 도달하지 않음)

        정렬: `(created_at DESC, post_id DESC)` — 컴파운드 인덱스와 일치, reverse-scan.
        cursor 는 마지막 row 의 `post_id` — `friend.repository.friendship` 의
        scalar_subquery 패턴 그대로 `created_at` 을 한 번 lookup 해 튜플 비교.
        """
        if not visibilities:
            # 빈 list 면 IN ([]) 가 되어 쿼리 자체가 의미 없음. 즉시 빈 결과.
            return []

        stmt = select(FeedPost).where(
            FeedPost.user_id == owner_id,
            FeedPost.visibility.in_(visibilities),
        )

        if cursor is not None:
            # 커서 row 의 created_at 을 같은 쿼리에 scalar_subquery 로 인라인.
            # (created_at < cur) OR (created_at == cur AND post_id < cur_id) — 안정 페이지네이션.
            cursor_sub = (
                select(FeedPost.created_at)
                .where(FeedPost.post_id == cursor)
                .scalar_subquery()
            )
            stmt = stmt.where(
                or_(
                    FeedPost.created_at < cursor_sub,
                    (FeedPost.created_at == cursor_sub) & (FeedPost.post_id < cursor),
                )
            )

        stmt = (
            stmt.order_by(FeedPost.created_at.desc(), FeedPost.post_id.desc())
            .limit(PAGE_SIZE)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


    # ──────────────────── Delete ────────────────────

    async def delete(self, post: FeedPost) -> None:
        """단건 삭제 — service 가 권한 검증 + storage prefix 삭제 후 호출.

        `feed_post_like` / `feed_post_comment` 는 ORM cascade (`all, delete-orphan`) +
        DB-level FK CASCADE 양쪽으로 자동 정리.
        """
        await self.session.delete(post)
