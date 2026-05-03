from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete

from app.domain.notification.model.fcm_token import FcmToken


class FcmTokenRepository:
    def __init__(self, session: AsyncSession):
        self.session = session


    # ──────────────────── Create ────────────────────

    async def save(self, fcm_token: FcmToken) -> FcmToken:
        """FCM 토큰 row 저장 (신규 등록).

        UNIQUE(token) 충돌 시 IntegrityError 가 raise 되므로,
        service 는 사전에 `find_by_token` 으로 존재 여부를 확인하고
        - 다른 user 소유면 `update()` 로 owner 만 교체
        - 같은 user 소유면 그대로 반환
        하는 흐름으로 처리한다.
        """
        self.session.add(fcm_token)
        await self.session.flush()
        return fcm_token


    # ──────────────────── Read ────────────────────

    async def find_by_token(self, token: str) -> Optional[FcmToken]:
        """token 단건 조회 — UNIQUE 제약상 0 또는 1 row."""
        stmt = select(FcmToken).where(FcmToken.token == token)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


    async def find_by_user_id(self, user_id: str) -> list[FcmToken]:
        """유저의 모든 디바이스 토큰 조회 — 푸시 발송 hot path 에서 사용.

        `ix_fcm_token_user_id` 인덱스로 O(log N) 조회.
        """
        stmt = select(FcmToken).where(FcmToken.user_id == user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


    # ──────────────────── Update ────────────────────

    async def update(self, fcm_token: FcmToken) -> FcmToken:
        """변경사항 flush — service 가 owner(user_id) 를 갱신한 뒤 호출."""
        await self.session.flush()
        return fcm_token


    # ──────────────────── Delete ────────────────────

    async def delete(self, fcm_token: FcmToken) -> None:
        """단건 삭제 — ORM 인스턴스 핸들이 있을 때."""
        await self.session.delete(fcm_token)


    async def delete_by_token(self, token: str) -> None:
        """token 문자열로 단건 삭제 — 클라이언트의 명시적 unregister 또는
        FCM 응답이 UNREGISTERED 일 때 fetch 없이 즉시 정리.
        """
        stmt = delete(FcmToken).where(FcmToken.token == token)
        await self.session.execute(stmt)


    async def delete_by_tokens(self, tokens: list[str]) -> None:
        """여러 token 일괄 삭제 — multicast 후 만료된 토큰들 정리에 사용."""
        if not tokens:
            return
        stmt = delete(FcmToken).where(FcmToken.token.in_(tokens))
        await self.session.execute(stmt)
