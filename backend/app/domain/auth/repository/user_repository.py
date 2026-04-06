from typing import Optional
from sqlalchemy import select
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


    async def save(self, user: User) -> User:
        self.session.add(user)
        await self.session.flush()
        return user


    async def delete(self, user: User) -> None:
        await self.session.delete(user)
