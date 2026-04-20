from typing import Optional
from sqlalchemy import select, or_, and_
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.friend.model.friendship import Friendship, FriendshipStatus
from app.domain.auth.model.user import User


# 친구/요청 목록 페이지 크기
PAGE_SIZE = 30


class FriendshipRepository:
    def __init__(self, session: AsyncSession):
        self.session = session


    # ──────────────────── Create ────────────────────

    async def save(self, friendship: Friendship) -> Friendship:
        """친구 관계 저장"""
        self.session.add(friendship)
        await self.session.flush()
        return friendship


    # ──────────────────── Read (단건) ────────────────────

    async def find_by_id(self, friendship_id: str) -> Optional[Friendship]:
        """friendship_id로 단건 조회"""
        return await self.session.get(Friendship, friendship_id)


    async def find_between(
        self,
        user_a_id: str,
        user_b_id: str,
    ) -> Optional[Friendship]:
        """두 유저 간의 친구 관계 (방향 무관) 단건 조회"""
        stmt = select(Friendship).where(
            or_(
                and_(
                    Friendship.requester_id == user_a_id,
                    Friendship.addressee_id == user_b_id,
                ),
                and_(
                    Friendship.requester_id == user_b_id,
                    Friendship.addressee_id == user_a_id,
                ),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


    # ──────────────────── Read (목록 — 커서 페이지네이션) ────────────────────

    async def find_friends(
        self,
        user_id: str,
        cursor: Optional[str] = None,
    ) -> list[Friendship]:
        """
        ACCEPTED 상태의 친구 목록 (requester 또는 addressee가 user_id인 경우)
        상대 프로필을 joinedload로 함께 로드
        """
        stmt = (
            select(Friendship)
            .options(
                joinedload(Friendship.requester).joinedload(User.detail),
                joinedload(Friendship.addressee).joinedload(User.detail),
            )
            .where(
                Friendship.status == FriendshipStatus.ACCEPTED,
                or_(
                    Friendship.requester_id == user_id,
                    Friendship.addressee_id == user_id,
                ),
            )
        )

        if cursor:
            cursor_sub = select(Friendship.updated_at).where(Friendship.friendship_id == cursor).scalar_subquery()
            stmt = stmt.where(
                or_(
                    Friendship.updated_at < cursor_sub,
                    (Friendship.updated_at == cursor_sub) & (Friendship.friendship_id < cursor),
                )
            )

        stmt = stmt.order_by(Friendship.updated_at.desc(), Friendship.friendship_id.desc()).limit(PAGE_SIZE)
        result = await self.session.execute(stmt)
        return list(result.unique().scalars().all())


    async def find_received_requests(
        self,
        user_id: str,
        cursor: Optional[str] = None,
    ) -> list[Friendship]:
        """내가 받은 PENDING 요청 목록 (요청자 프로필 포함)"""
        stmt = (
            select(Friendship)
            .options(joinedload(Friendship.requester).joinedload(User.detail))
            .where(
                Friendship.addressee_id == user_id,
                Friendship.status == FriendshipStatus.PENDING,
            )
        )

        if cursor:
            cursor_sub = select(Friendship.updated_at).where(Friendship.friendship_id == cursor).scalar_subquery()
            stmt = stmt.where(
                or_(
                    Friendship.updated_at < cursor_sub,
                    (Friendship.updated_at == cursor_sub) & (Friendship.friendship_id < cursor),
                )
            )

        stmt = stmt.order_by(Friendship.updated_at.desc(), Friendship.friendship_id.desc()).limit(PAGE_SIZE)
        result = await self.session.execute(stmt)
        return list(result.unique().scalars().all())


    async def find_sent_requests(
        self,
        user_id: str,
        cursor: Optional[str] = None,
    ) -> list[Friendship]:
        """내가 보낸 PENDING 요청 목록 (수신자 프로필 포함)"""
        stmt = (
            select(Friendship)
            .options(joinedload(Friendship.addressee).joinedload(User.detail))
            .where(
                Friendship.requester_id == user_id,
                Friendship.status == FriendshipStatus.PENDING,
            )
        )

        if cursor:
            cursor_sub = select(Friendship.updated_at).where(Friendship.friendship_id == cursor).scalar_subquery()
            stmt = stmt.where(
                or_(
                    Friendship.updated_at < cursor_sub,
                    (Friendship.updated_at == cursor_sub) & (Friendship.friendship_id < cursor),
                )
            )

        stmt = stmt.order_by(Friendship.updated_at.desc(), Friendship.friendship_id.desc()).limit(PAGE_SIZE)
        result = await self.session.execute(stmt)
        return list(result.unique().scalars().all())


    # ──────────────────── Update ────────────────────

    async def update(self, friendship: Friendship) -> Friendship:
        """변경사항 flush"""
        await self.session.flush()
        return friendship


    # ──────────────────── Delete ────────────────────

    async def delete(self, friendship: Friendship) -> None:
        """친구 관계 삭제"""
        await self.session.delete(friendship)
