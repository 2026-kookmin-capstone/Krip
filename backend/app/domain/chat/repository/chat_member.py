from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import func, select, update

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


    async def find_last_read_seqs(
        self,
        user_id: str,
        room_ids: Optional[list[str]] = None,
    ) -> dict[str, int]:
        """유저의 방별 `last_read_message_server_seq` 배치 조회 (is_left=false 만).

        unread 복구 전용 — "내가 아직 안 읽은 메시지" 를 Mongo 에서 카운트하려면
        방별 마지막 읽은 seq 가 필요하다.

        NULL 인 경우 0 으로 돌려 "0 초과" 즉 "전체 메시지" 가 미읽음 카운트 대상이 되게 함
        (`GREATEST(COALESCE(..., 0), ...)` 와 같은 관점).

        Args:
            user_id: 복구 대상 유저
            room_ids: 특정 방들로 한정 (재초대 플로우 등). `None` 이면 유저의 활성 방 전체

        Returns:
            `{chat_room_id: last_read_seq}`. is_left=true 이거나 미가입 방은 포함 안 됨.
        """
        conditions = [
            ChatRoomMember.user_id == user_id,
            ChatRoomMember.is_left.is_(False),
        ]
        if room_ids is not None:
            if not room_ids:
                return {}
            conditions.append(ChatRoomMember.chat_room_id.in_(room_ids))

        stmt = select(
            ChatRoomMember.chat_room_id,
            ChatRoomMember.last_read_message_server_seq,
        ).where(*conditions)
        result = await self.session.execute(stmt)
        return {row[0]: int(row[1] or 0) for row in result.all()}


    # ──────────────────── Update ────────────────────

    async def update(self, member: ChatRoomMember) -> ChatRoomMember:
        """변경사항 flush"""
        await self.session.flush()
        return member


    async def mark_read(
        self, chat_room_id: str, user_id: str, new_seq: int,
    ) -> Optional[int]:
        """`last_read_message_server_seq` 를 `GREATEST(COALESCE(기존, 0), new_seq)` 로 갱신.

        - `is_left=false` 인 활성 멤버 row 에만 반영 — 탈퇴자의 읽음 갱신은 의미 없음.
        - RETURNING 으로 갱신 후 최종 seq 를 돌려받아 클라 ACK 에 사용.
        - 동일 유저가 여러 세션에서 동시에 다른 seq 로 read 를 보낼 때 regress 방지 —
          과거 seq 가 DB 에 내려오더라도 `GREATEST` 가 한 번에 올라간 포인터를 지킨다.
        - `synchronize_session=False` — 시스템 메시지 처리 시 `update_last_message`
          에서 같은 이유로 채택한 선택과 동일 (§Phase 2 #2 디버깅 노트).

        Returns:
            갱신된 `last_read_message_server_seq`. 활성 멤버가 아니면 None.
        """
        stmt = (
            update(ChatRoomMember)
            .where(
                ChatRoomMember.chat_room_id == chat_room_id,
                ChatRoomMember.user_id == user_id,
                ChatRoomMember.is_left.is_(False),
            )
            .values(
                last_read_message_server_seq=func.greatest(
                    func.coalesce(ChatRoomMember.last_read_message_server_seq, 0),
                    new_seq,
                ),
                last_read_at=func.now(),
            )
            .returning(ChatRoomMember.last_read_message_server_seq)
            .execution_options(synchronize_session=False)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


    async def count_readers_up_to(
        self,
        chat_room_id: str,
        server_seq: int,
        exclude_user_id: str,
    ) -> int:
        """특정 `server_seq` 이상 읽은 활성 멤버 수 (발신자 본인 제외).

        카톡 미읽음 숫자 뱃지 = "방 활성 멤버 수 - (이 카운트 + 1)" 공식의 그 카운트.
        지금은 라우터에서 쓰진 않지만 실시간 fan-out 만으로는 정확하지 않을 때 API 경로에서 
        권위있는 값을 돌려주는 용도로 확장.
        """
        stmt = select(func.count()).select_from(ChatRoomMember).where(
            ChatRoomMember.chat_room_id == chat_room_id,
            ChatRoomMember.is_left.is_(False),
            ChatRoomMember.user_id != exclude_user_id,
            ChatRoomMember.last_read_message_server_seq >= server_seq,
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())
