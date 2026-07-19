from datetime import datetime
from typing import Optional

from sqlalchemy import case, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.chat.model.chat_room import ChatRoom, ChatRoomType
from app.domain.chat.model.chat_room_member import ChatRoomMember
from app.util.cursor import decode_cursor, keyset_where


PAGE_SIZE = 500


class ChatRoomRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, chat_room: ChatRoom) -> ChatRoom:
        """채팅방 insert. DIRECT 동시 생성 race 는 UNIQUE 위반 → 호출측 SAVEPOINT + 재조회."""
        self.session.add(chat_room)
        await self.session.flush()
        return chat_room

    async def find_by_id(self, chat_room_id: str) -> Optional[ChatRoom]:
        """chat_room_id 로 단건 조회"""
        return await self.session.get(ChatRoom, chat_room_id)

    async def find_by_id_for_update(self, chat_room_id: str) -> Optional[ChatRoom]:
        """membership mutation과 메시지 seq commit 순서 직렬화용 room row X-lock."""
        stmt = (
            select(ChatRoom)
            .where(ChatRoom.chat_room_id == chat_room_id)
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_direct_by_pair(
        self,
        user_a_id: str,
        user_b_id: str,
    ) -> Optional[ChatRoom]:
        """canonical 정렬된 DIRECT 방 조회. 호출측이 `a < b` 로 정렬해서 넘겨야 한다.

        탈퇴로 한 쪽이 NULL 인 방은 매칭되지 않음 — 의도적으로 "새 방 생성 대상" 처리.
        """
        stmt = select(ChatRoom).where(
            ChatRoom.type == ChatRoomType.DIRECT,
            ChatRoom.direct_user_a_id == user_a_id,
            ChatRoom.direct_user_b_id == user_b_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_rooms_of_user(
        self,
        user_id: str,
        cursor: Optional[str] = None,
        limit: int = PAGE_SIZE,
    ) -> list[tuple[ChatRoom, Optional[str], Optional[bool]]]:
        """유저의 활성 방 목록 (`effective_last_at`, `chat_room_id`) DESC.

        반환: `(ChatRoom, peer_user_id, notification_muted)` — JOIN 으로 mute 까지 N+1 없이 한 번에.
        1:1 의 peer 는 함께 계산, 그룹은 None.
        """
        # 1:1 의 상대방 user_id 파생 (내가 a 면 b, b 면 a, 그룹이면 None).
        peer_user_id = case(
            (
                ChatRoom.type == ChatRoomType.DIRECT,
                case(
                    (ChatRoom.direct_user_a_id == user_id, ChatRoom.direct_user_b_id),
                    else_=ChatRoom.direct_user_a_id,
                ),
            ),
            else_=None,
        ).label("peer_user_id")

        stmt = (
            select(ChatRoom, peer_user_id, ChatRoomMember.notification_muted)
            .join(ChatRoomMember, ChatRoomMember.chat_room_id == ChatRoom.chat_room_id)
            .where(
                ChatRoomMember.user_id == user_id,
                ChatRoomMember.is_left.is_(False),
            )
        )

        if cursor:
            decoded = decode_cursor(cursor)
            if (
                decoded is None
                or decoded[0].tzinfo is None
                or decoded[0].utcoffset() is None
            ):
                raise ValueError("유효하지 않은 커서입니다.")
            sort_value, room_id = decoded
            stmt = stmt.where(keyset_where(
                ChatRoom.effective_last_at,
                ChatRoom.chat_room_id,
                sort_value,
                room_id,
            ))

        stmt = stmt.order_by(
            ChatRoom.effective_last_at.desc(),
            ChatRoom.chat_room_id.desc(),
        ).limit(limit)

        result = await self.session.execute(stmt)
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def update_last_message_if_greater(
        self,
        chat_room_id: str,
        message_id: str,
        server_seq: int,
        at: datetime,
    ) -> None:
        """reconcile 전용 — 송신과 병렬로 돌 수 있어 단순 덮어쓰기는 regress 위험.

        `WHERE seq IS NULL OR seq < new` 가드로 기존 ≥ new 면 no-op.
        """
        stmt = (
            update(ChatRoom)
            .where(
                ChatRoom.chat_room_id == chat_room_id,
                or_(
                    ChatRoom.last_message_server_seq.is_(None),
                    ChatRoom.last_message_server_seq < server_seq,
                ),
            )
            .values(
                last_message_id=message_id,
                last_message_server_seq=server_seq,
                last_message_at=at,
            )
            .execution_options(synchronize_session=False)
        )
        await self.session.execute(stmt)
