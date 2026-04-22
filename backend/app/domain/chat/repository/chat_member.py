from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.domain.chat.model.chat_room_member import ChatRoomMember


class ChatRoomMemberRepository:
    def __init__(self, session: AsyncSession):
        self.session = session


    # ──────────────────── Create ────────────────────

    async def save(self, member: ChatRoomMember) -> ChatRoomMember:
        """방 멤버 1건 insert"""
        self.session.add(member)
        await self.session.flush()
        return member


    async def save_all(self, members: list[ChatRoomMember]) -> list[ChatRoomMember]:
        """여러 멤버 한 번에 insert — 방 생성 직후 creator + 초대 멤버 일괄 등록용"""
        self.session.add_all(members)
        await self.session.flush()
        return members


    # ──────────────────── Read (단건) ────────────────────

    async def find(
        self,
        chat_room_id: str,
        user_id: str,
    ) -> Optional[ChatRoomMember]:
        """복합 PK 로 단건 조회 (is_left 여부와 무관)"""
        return await self.session.get(ChatRoomMember, (chat_room_id, user_id))


    # ──────────────────── Read (목록) ────────────────────

    async def find_active_member_ids(self, chat_room_id: str) -> list[str]:
        """방의 활성 멤버 user_id 목록 (is_left=false).

        `room:members:{R}` 캐시 miss 경로에서 사용 — 전체를 한 번에
        로드해 SADD 하도록 한다. 개별 조회(한 명씩) 금지.
        """
        stmt = select(ChatRoomMember.user_id).where(
            ChatRoomMember.chat_room_id == chat_room_id,
            ChatRoomMember.is_left.is_(False),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


    async def is_active_member(self, chat_room_id: str, user_id: str) -> bool:
        """유저가 특정 방의 활성 멤버인지 확인 (is_left=false). 권한 체크용 단발성 조회."""
        stmt = select(ChatRoomMember.user_id).where(
            ChatRoomMember.chat_room_id == chat_room_id,
            ChatRoomMember.user_id == user_id,
            ChatRoomMember.is_left.is_(False),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None


    async def find_user_room_ids(self, user_id: str) -> list[str]:
        """유저가 속한 활성 방 ID 목록 (is_left=false). WS 연결 시 초기 방 구독용."""
        stmt = select(ChatRoomMember.chat_room_id).where(
            ChatRoomMember.user_id == user_id,
            ChatRoomMember.is_left.is_(False),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


    # ──────────────────── Update ────────────────────

    async def update(self, member: ChatRoomMember) -> ChatRoomMember:
        """변경사항 flush"""
        await self.session.flush()
        return member
