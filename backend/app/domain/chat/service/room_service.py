"""채팅방 생성 / 멤버십 관리 서비스.

Phase 1 에서는 **1:1 방 생성** 만. 그룹 방 / 초대 / 퇴장 은 Phase 2 에서 이 서비스에
추가 예정. room_joined 이벤트 발행으로 양쪽 유저의 WS 가 로컬 dict 에 방을 등록하게 한다.
"""
from sqlalchemy.exc import IntegrityError

from app.domain.auth.repository.user import UserRepository
from app.domain.chat.dto.room import ChatRoomData, ChatRoomPeerData
from app.domain.chat.model.chat_room import ChatRoom, ChatRoomType
from app.domain.chat.model.chat_room_member import ChatRoomMember
from app.domain.chat.repository.chat_room import ChatRoomRepository
from app.domain.chat.repository.chat_member import ChatRoomMemberRepository
from app.domain.friend.repository.user_block import UserBlockRepository
from app.database.session import UnitOfWork, transactional
from app.core.chat.redis_keys import room_members_key, ROOM_MEMBERS_TTL
from app.core.logger import get_logger
from app.core.redis import get_redis_client


logger = get_logger("chat.room")


class RoomService:
    """채팅방 생명주기 — 생성·멤버 등록·구독 이벤트 발행."""

    def __init__(self, uow: UnitOfWork, fanout_service):
        # fanout_service 는 type hint 생략 (순환 import 회피)
        self.uow = uow
        self._fanout = fanout_service


    # ──────────────────── 1:1 방 생성 ────────────────────

    @transactional
    async def create_direct_room(self, me_id: str, peer_user_id: str) -> ChatRoomData:
        """1:1 방 idempotent 생성.

        순서:
        1. 자기 자신과의 방 금지
        2. 상대 유저 존재 검증
        3. 차단 관계 검증 (양방향 한 번에 — 상호 차단이어도 내 차단을 우선 안내)
        4. canonical 정렬된 (a, b) 로 기존 방 조회
        5. 없으면 SAVEPOINT 로 INSERT — UNIQUE race 는 IntegrityError 재조회로 복구
        6. Redis `room:members:{R}` 캐시 + 양쪽 유저에 `room_joined` 이벤트 발행
        """
        if me_id == peer_user_id:
            raise ValueError("자기 자신과의 방은 만들 수 없습니다.")

        chat_room_repo = ChatRoomRepository(self._session)
        member_repo = ChatRoomMemberRepository(self._session)
        block_repo = UserBlockRepository(self._session)
        user_repo = UserRepository(self._session)

        # 상대 유저 존재 (탈퇴자 선점 UX 를 위해 detail 조인 사용)
        peer = await user_repo.find_by_id_with_profile(peer_user_id)
        if peer is None:
            raise ValueError("존재하지 않는 유저입니다.")

        # 차단 관계 검증 (양방향)
        blocks = await block_repo.find_blocks_between(me_id, peer_user_id)
        if any(b.blocker_id == me_id for b in blocks):
            raise ValueError("차단한 유저와는 방을 만들 수 없습니다. 먼저 차단을 해제해주세요.")
        if blocks:
            raise ValueError("해당 유저와는 방을 만들 수 없습니다.")

        # canonical 정렬
        user_a, user_b = sorted([me_id, peer_user_id])

        # 기존 방 재활용 (idempotent)
        existing = await chat_room_repo.find_direct_by_pair(user_a, user_b)
        if existing is not None:
            return await self._to_dto(existing, me_id=me_id, peer=peer)

        # 새 방 생성 — UNIQUE race 시 SAVEPOINT rollback + 재조회
        new_room = ChatRoom(
            type=ChatRoomType.DIRECT,
            creator_id=me_id,
            direct_user_a_id=user_a,
            direct_user_b_id=user_b,
        )
        try:
            async with self._session.begin_nested():
                await chat_room_repo.save(new_room)
                await member_repo.save_all([
                    ChatRoomMember(chat_room_id=new_room.chat_room_id, user_id=user_a),
                    ChatRoomMember(chat_room_id=new_room.chat_room_id, user_id=user_b),
                ])
        except IntegrityError:
            existing = await chat_room_repo.find_direct_by_pair(user_a, user_b)
            if existing is None:
                raise ValueError("방 생성 경합 실패. 잠시 후 다시 시도해주세요.")
            return await self._to_dto(existing, me_id=me_id, peer=peer)

        # Redis 멤버 캐시 + 양쪽 유저에 room_joined 이벤트
        room_id = new_room.chat_room_id
        redis = await get_redis_client()
        pipe = redis.pipeline(transaction=True)
        pipe.sadd(room_members_key(room_id), user_a, user_b)
        pipe.expire(room_members_key(room_id), ROOM_MEMBERS_TTL)
        await pipe.execute()

        # 본인 포함 양쪽에 발행 — 같은 유저의 다른 세션 (폰→PC) 도 자동 구독되도록 (C3)
        for uid in (user_a, user_b):
            await self._fanout.fan_out_to_user(
                uid,
                {"type": "room_joined", "room_id": room_id},
            )

        logger.info("1:1 방 생성 완료: room_id={}, a={}, b={}", room_id, user_a, user_b)
        return await self._to_dto(new_room, me_id=me_id, peer=peer)


    # ──────────────────── WS 연결 시 초기 방 구독용 ────────────────────

    @transactional
    async def list_user_room_ids(self, user_id: str) -> list[str]:
        """유저가 속한 활성 방 ID 목록. WS 연결 직후 `register_ws_to_room` 호출에 사용."""
        member_repo = ChatRoomMemberRepository(self._session)
        return await member_repo.find_user_room_ids(user_id)


    # ──────────────────── 내부 변환 ────────────────────

    @staticmethod
    async def _to_dto(room: ChatRoom, me_id: str, peer) -> ChatRoomData:
        """DTO 변환. 신규 1:1 방은 last_message 가 항상 None."""
        # peer 가 User ORM 객체 (User + detail) 로 오는 경우 detail 에서 user_name 추출
        peer_dto = ChatRoomPeerData(
            user_id=peer.user_id,
            user_name=peer.detail.user_name if peer.detail else None,
        )
        return ChatRoomData(
            chat_room_id=room.chat_room_id,
            type=room.type,
            title=room.title,
            peer=peer_dto,
            last_message=None,
            unread_count=0,
            last_message_at=room.last_message_at,
            effective_last_at=room.effective_last_at or room.created_at,
        )
