from datetime import datetime
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.domain.auth.model.user import User, UserStatus
from app.domain.chat.model.chat_room_member import ChatRoomMember


class ChatRoomMemberRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, member: ChatRoomMember) -> ChatRoomMember:
        self.session.add(member)
        await self.session.flush()
        return member

    async def save_all(self, members: list[ChatRoomMember]) -> list[ChatRoomMember]:
        """방 생성 직후 creator + 초대 멤버 일괄 등록."""
        self.session.add_all(members)
        await self.session.flush()
        return members

    async def find(
        self,
        chat_room_id: str,
        user_id: str,
    ) -> Optional[ChatRoomMember]:
        """복합 PK 단건 조회 (is_left 여부 무관)."""
        return await self.session.get(ChatRoomMember, (chat_room_id, user_id))

    async def find_for_update(
        self, chat_room_id: str, user_id: str,
    ) -> Optional[ChatRoomMember]:
        """leave/kick 상태 전이를 같은 membership row의 exclusive lock으로 직렬화."""
        stmt = (
            select(ChatRoomMember)
            .where(
                ChatRoomMember.chat_room_id == chat_room_id,
                ChatRoomMember.user_id == user_id,
            )
            .with_for_update()
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_active_member_users(self, chat_room_id: str) -> list[User]:
        """방의 활성 멤버 User + detail 을 joined_at ASC 로 (참여자 목록 노출용)."""
        stmt = (
            select(User)
            .options(joinedload(User.detail))
            .join(ChatRoomMember, ChatRoomMember.user_id == User.user_id)
            .where(
                ChatRoomMember.chat_room_id == chat_room_id,
                ChatRoomMember.is_left.is_(False),
            )
            .order_by(ChatRoomMember.joined_at.asc(), User.user_id.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.unique().scalars().all())

    async def find_active_member_ids(self, chat_room_id: str) -> list[str]:
        """방의 활성 멤버 user_id 목록 — `room:members:{R}` 캐시 miss 시 일괄 로드용."""
        stmt = select(ChatRoomMember.user_id).where(
            ChatRoomMember.chat_room_id == chat_room_id,
            ChatRoomMember.is_left.is_(False),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_active_membership_generations(
        self, chat_room_id: str,
    ) -> dict[str, datetime]:
        """room lock 아래 post-commit delivery에 결합할 active generation snapshot."""
        stmt = select(
            ChatRoomMember.user_id, ChatRoomMember.joined_at,
        ).where(
            ChatRoomMember.chat_room_id == chat_room_id,
            ChatRoomMember.is_left.is_(False),
        )
        rows = (await self.session.execute(stmt)).all()
        return {row.user_id: row.joined_at for row in rows}

    async def lock_active_receiving_user_ids(
        self, chat_room_id: str, user_ids: set[str],
    ) -> set[str]:
        """수신 완료까지 퇴장·계정 비활성화 update를 막는 권한 projection."""
        if not user_ids:
            return set()
        stmt = (
            select(ChatRoomMember.user_id)
            .join(User, User.user_id == ChatRoomMember.user_id)
            .where(
                ChatRoomMember.chat_room_id == chat_room_id,
                ChatRoomMember.user_id.in_(user_ids),
                ChatRoomMember.is_left.is_(False),
                User.status == UserStatus.ACTIVE,
            )
            .with_for_update(read=True, of=(ChatRoomMember, User))
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def lock_active_member_user_ids(
        self, chat_room_id: str, user_ids: set[str],
    ) -> set[str]:
        """membership side effect 완료까지 현재 active member rows를 공유 잠금한다."""
        if not user_ids:
            return set()
        stmt = (
            select(ChatRoomMember.user_id)
            .where(
                ChatRoomMember.chat_room_id == chat_room_id,
                ChatRoomMember.user_id.in_(user_ids),
                ChatRoomMember.is_left.is_(False),
            )
            .with_for_update(read=True)
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def lock_matching_membership_generations(
        self,
        chat_room_id: str,
        expected: dict[str, datetime],
        *,
        is_left: bool,
    ) -> set[str]:
        """post-commit effect를 정확한 membership generation에 결합한다."""
        if not expected:
            return set()
        stmt = (
            select(ChatRoomMember.user_id, ChatRoomMember.joined_at)
            .where(
                ChatRoomMember.chat_room_id == chat_room_id,
                ChatRoomMember.user_id.in_(expected),
                ChatRoomMember.is_left.is_(is_left),
            )
            .order_by(ChatRoomMember.user_id)
            .with_for_update(read=True)
        )
        rows = (await self.session.execute(stmt)).all()
        return {
            row.user_id
            for row in rows
            if row.joined_at == expected[row.user_id]
        }

    async def lock_receiving_state(self, chat_room_id: str, user_id: str) -> bool:
        """구독 변경 적용까지 inactive row도 잠그고 현재 수신 가능 상태를 반환한다."""
        stmt = (
            select(ChatRoomMember.is_left, User.status)
            .join(User, User.user_id == ChatRoomMember.user_id)
            .where(
                ChatRoomMember.chat_room_id == chat_room_id,
                ChatRoomMember.user_id == user_id,
            )
            .with_for_update(read=True, of=(ChatRoomMember, User))
        )
        result = await self.session.execute(stmt)
        row = result.one_or_none()
        return row is not None and not row.is_left and row.status == UserStatus.ACTIVE

    async def lock_active_room_ids_for_user(
        self, user_id: str, chat_room_ids: set[str],
    ) -> set[str]:
        """unread metadata 전송까지 현재 active membership rows를 공유 잠금한다."""
        if not chat_room_ids:
            return set()
        stmt = (
            select(ChatRoomMember.chat_room_id)
            .where(
                ChatRoomMember.user_id == user_id,
                ChatRoomMember.chat_room_id.in_(chat_room_ids),
                ChatRoomMember.is_left.is_(False),
            )
            .with_for_update(read=True)
        )
        result = await self.session.execute(stmt)
        return set(result.scalars().all())

    async def count_active_members(self, chat_room_id: str) -> int:
        stmt = select(func.count()).select_from(ChatRoomMember).where(
            ChatRoomMember.chat_room_id == chat_room_id,
            ChatRoomMember.is_left.is_(False),
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def is_active_member(self, chat_room_id: str, user_id: str) -> bool:
        """활성 멤버 여부 (is_left=false). 권한 체크용."""
        stmt = select(ChatRoomMember.user_id).where(
            ChatRoomMember.chat_room_id == chat_room_id,
            ChatRoomMember.user_id == user_id,
            ChatRoomMember.is_left.is_(False),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def is_active_member_for_share(self, chat_room_id: str, user_id: str) -> bool:
        """퇴장·강퇴 update와 송신 권한 판정을 공유 잠금으로 직렬화."""
        stmt = (
            select(ChatRoomMember.user_id)
            .where(
                ChatRoomMember.chat_room_id == chat_room_id,
                ChatRoomMember.user_id == user_id,
                ChatRoomMember.is_left.is_(False),
            )
            .with_for_update(read=True)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def find_pushable_user_ids_in_room(
        self,
        chat_room_id: str,
        user_ids: list[str],
        expected_generations: dict[str, datetime] | None = None,
    ) -> set[str]:
        """푸시 완료까지 활성 계정·동일 membership generation을 share-lock한다."""
        if not user_ids:
            return set()
        account_stmt = (
            select(User.user_id)
            .where(
                User.user_id.in_(user_ids),
                User.status == UserStatus.ACTIVE,
            )
            .order_by(User.user_id)
            .with_for_update(read=True)
        )
        active_user_ids = set(
            (await self.session.execute(account_stmt)).scalars().all()
        )
        if not active_user_ids:
            return set()

        member_stmt = (
            select(ChatRoomMember.user_id, ChatRoomMember.joined_at)
            .where(
                ChatRoomMember.chat_room_id == chat_room_id,
                ChatRoomMember.user_id.in_(active_user_ids),
                ChatRoomMember.is_left.is_(False),
                ChatRoomMember.notification_muted.is_not(True),
            )
            .order_by(ChatRoomMember.user_id)
            .with_for_update(read=True)
        )
        rows = (await self.session.execute(member_stmt)).all()
        return {
            row.user_id
            for row in rows
            if expected_generations is None
            or row.joined_at == expected_generations.get(row.user_id)
        }

    async def find_user_room_ids(self, user_id: str) -> list[str]:
        """유저가 속한 활성 방 ID. WS 연결 시 초기 구독용."""
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
        *,
        for_share: bool = False,
    ) -> dict[str, int]:
        """유저의 방별 `last_read_message_server_seq` 배치 조회 — unread 복구 전용.

        NULL 은 0 으로 정규화 → "전체 메시지" 가 미읽음 카운트 대상이 됨.
        `room_ids=None` 이면 활성 방 전체.
        `for_share=True`이면 generation 캡처까지 퇴장 update를 막는다.
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
        if for_share:
            stmt = stmt.with_for_update(read=True)
        result = await self.session.execute(stmt)
        return {row[0]: int(row[1] or 0) for row in result.all()}

    async def update(self, member: ChatRoomMember) -> ChatRoomMember:
        await self.session.flush()
        return member

    async def mark_read(
        self, chat_room_id: str, user_id: str, new_seq: int,
    ) -> Optional[int]:
        """`last_read_message_server_seq = GREATEST(COALESCE(기존, 0), new_seq)`.

        활성 멤버 row 에만 반영 — 탈퇴자는 None 반환.
        RETURNING 으로 최종 seq 를 돌려받아 ACK 에 사용.
        다중 세션에서 다른 seq 로 동시 read 가 와도 GREATEST 가 regress 차단.
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
