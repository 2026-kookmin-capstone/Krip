from typing import Optional
from sqlalchemy import select, delete
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.auth.model.user import User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session


    async def find_by_id(self, user_id: str) -> Optional[User]:
        return await self.session.get(User, user_id)


    async def find_by_provider(self, auth_provider: str, auth_provider_id: str) -> Optional[User]:
        stmt = select(User).where(
            User.auth_provider == auth_provider,
            User.auth_provider_id == auth_provider_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


    async def find_by_id_with_profile(self, user_id: str) -> Optional[User]:
        """유저 + 상세정보 + 여행스타일을 한 번에 조회"""
        stmt = select(User).options(
            joinedload(User.detail),
            joinedload(User.travel_styles),
        ).where(User.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.unique().scalar_one_or_none()


    async def save(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user


    async def delete(self, user: User) -> None:
        await self.session.delete(user)


    async def hard_delete_by_id(self, user_id: str) -> bool:
        """유저 하드 탈퇴 — DB CASCADE로 연관 데이터 전체 삭제

        삭제 대상 (모두 FK ondelete="CASCADE"):
            - user_detail_inform (프로필)
            - user_travel_style (여행 스타일)
            - tripmate_post (게시글) → tripmate_post_image, tripmate_post_like
            - tripmate_post_like (좋아요 누른 입장)
            - favorite_place (즐겨찾기)
            - friendship (requester/addressee 양측)
            - user_block (blocker/blocked 양측)
        """
        stmt = delete(User).where(User.user_id == user_id)
        result = await self.session.execute(stmt)
        return result.rowcount > 0
