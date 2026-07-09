from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

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

    async def prune_user_tokens_keeping_latest(self, *, user_id: str, keep: int) -> int:
        """유저의 토큰을 updated_at 최신순 `keep` 개만 남기고 삭제. 삭제한 행 수 반환.

        OFFSET 서브쿼리로 상위 keep 개를 건너뛴 나머지를 DELETE — 방금 upsert 한
        (updated_at=now) 토큰은 항상 상위에 들어 보존된다.
        """
        stale = (
            select(FcmToken.fcm_token_id)
            .where(FcmToken.user_id == user_id)
            .order_by(FcmToken.updated_at.desc(), FcmToken.fcm_token_id.desc())
            .offset(keep)
        )
        stmt = delete(FcmToken).where(FcmToken.fcm_token_id.in_(stale))
        result = await self.session.execute(stmt)
        return result.rowcount or 0
