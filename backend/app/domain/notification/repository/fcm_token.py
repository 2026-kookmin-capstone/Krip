from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import select, delete, func

from app.domain.notification.model.fcm_token import FcmToken


class FcmTokenRepository:
    def __init__(self, session: AsyncSession):
        self.session = session


    async def upsert_by_token(self, *, user_id: str, token: str) -> FcmToken:
        """UNIQUE(token) 충돌 시 owner 만 교체 — 단일 SQL 로 race 회피 (계정 A→B 재로그인 포함)."""
        stmt = (
            pg_insert(FcmToken)
            .values(user_id=user_id, token=token)
            .on_conflict_do_update(
                index_elements=["token"],
                set_={"user_id": user_id, "updated_at": func.now()},
            )
            .returning(FcmToken)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one()


    async def find_by_user_ids(self, user_ids: list[str]) -> list[FcmToken]:
        """그룹방 fan-out bulk."""
        if not user_ids:
            return []
        stmt = select(FcmToken).where(FcmToken.user_id.in_(user_ids))
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


    async def delete_by_user_token(self, *, user_id: str, token: str) -> None:
        """본인 소유만 삭제 — owner 불일치/미존재면 0 row, 멱등."""
        stmt = delete(FcmToken).where(
            FcmToken.token == token,
            FcmToken.user_id == user_id,
        )
        await self.session.execute(stmt)


    async def delete_by_tokens(self, tokens: list[str]) -> None:
        """multicast 후 만료 토큰 bulk 정리."""
        if not tokens:
            return
        stmt = delete(FcmToken).where(FcmToken.token.in_(tokens))
        await self.session.execute(stmt)
