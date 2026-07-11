"""채팅방 생성 / 멤버십 / 읽음 처리."""
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from app.core.chat.lua_script import lua_scripts
from app.core.chat.redis_key import (
    ROOM_MEMBERS_TTL,
    read_sync_key,
    room_members_gen_key,
    room_members_key,
    room_seq_key,
    unread_key,
)
from app.core.logger import get_logger
from app.core.redis import get_redis_client
from app.database.session import UnitOfWork, mongodb, transactional
from app.domain.auth.repository.user import UserRepository
from app.domain.chat.constants import (
    MAX_GROUP_MEMBERS,
    UNREAD_COUNT_CAP,
    UNREAD_COUNT_LIMIT,
)
from app.domain.chat.dto.room import ChatRoomData, ChatRoomPeerData
from app.domain.chat.model.chat_room import ChatRoom, ChatRoomType
from app.domain.chat.model.chat_room_member import ChatRoomMember
from app.domain.chat.repository.chat_member import ChatRoomMemberRepository
from app.domain.chat.repository.chat_message import ChatMessageRepository
from app.domain.chat.repository.chat_room import ChatRoomRepository
from app.domain.chat.service.exception import ChatRoomNotFoundError
from app.domain.friend.repository.friendship import FriendshipRepository
from app.domain.friend.repository.user_block import UserBlockRepository


logger = get_logger("chat.room")


class RoomService:
    """채팅방 생명주기 — 생성·멤버 등록·구독 이벤트 발행."""

    def __init__(self, uow: UnitOfWork, fanout_service, message_service):
        # fanout_service / message_service 는 type hint 생략 — 순환 import 회피.
        self.uow = uow
        self._fanout = fanout_service
        self._message_service = message_service

    async def create_direct_room(self, me_id: str, peer_user_id: str) -> ChatRoomData:
        """1:1 방 idempotent 생성. canonical 정렬 `(a<b)` 로 같은 쌍은 항상 같은 방.

        Redis 캐시/구독/fan-out 은 트랜잭션 커밋 이후 실행 — 커밋 롤백 시 비멤버가 Redis
        캐시에 남아 송수신 가능한 상태(최대 TTL)를 방지.
        """
        new_room_id, members, dto = await self._create_direct_room_tx(
            me_id=me_id, peer_user_id=peer_user_id,
        )
        if new_room_id is not None:
            await self._run_side_effect_safe(
                self._emit_room_joined(new_room_id, list(members), unread_seed=None),
                room_id=new_room_id, label="room_joined:direct",
            )
            logger.info("1:1 방 생성 완료: room_id={}, members={}", new_room_id, members)
        return dto

    @transactional
    async def _create_direct_room_tx(
        self, *, me_id: str, peer_user_id: str,
    ) -> tuple[str | None, tuple[str, str] | None, ChatRoomData]:
        """1:1 방 생성 DB 파트. 신규면 (room_id, (a,b), dto), 기존/경합이면 (None, None, dto)."""
        if me_id == peer_user_id:
            raise ValueError("자기 자신과의 방은 만들 수 없습니다.")

        chat_room_repo = ChatRoomRepository(self._session)
        member_repo = ChatRoomMemberRepository(self._session)
        block_repo = UserBlockRepository(self._session)
        user_repo = UserRepository(self._session)

        peer = await user_repo.find_by_id_with_profile(peer_user_id)
        if peer is None:
            raise ValueError("존재하지 않는 유저입니다.")

        blocks = await block_repo.find_blocks_between(me_id, peer_user_id)
        if any(b.blocker_id == me_id for b in blocks):
            raise ValueError("차단한 유저와는 방을 만들 수 없습니다. 먼저 차단을 해제해주세요.")
        if blocks:
            raise ValueError("해당 유저와는 방을 만들 수 없습니다.")

        user_a, user_b = sorted([me_id, peer_user_id])

        existing = await chat_room_repo.find_direct_by_pair(user_a, user_b)
        if existing is not None:
            return None, None, await self._to_dto(existing, me_id=me_id, peer=peer)

        # UNIQUE race 는 SAVEPOINT rollback + 재조회로 idempotent 처리.
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
            return None, None, await self._to_dto(existing, me_id=me_id, peer=peer)

        dto = await self._to_dto(new_room, me_id=me_id, peer=peer)
        return new_room.chat_room_id, (user_a, user_b), dto

    async def _emit_room_joined(
        self, room_id: str, member_ids: list[str], *, unread_seed: str | None,
    ) -> None:
        """(커밋 후) room:members 캐시 SADD + unread 초기화 + 구독 + room_joined fan-out.

        구독을 fan-out 보다 먼저 — await 사이 누군가 송신해도 미구독 멤버 누락 방지.
        unread_seed="zero" 면 각 멤버 unread 를 0 으로 초기화(그룹 생성용).
        """
        redis = await get_redis_client()
        pipe = redis.pipeline(transaction=True)
        # gen INCR — 멤버십 변경 신호. 진행 중인 stale read-repair populate 를 무효화한다.
        pipe.incr(room_members_gen_key(room_id))
        pipe.sadd(room_members_key(room_id), *member_ids)
        pipe.expire(room_members_key(room_id), ROOM_MEMBERS_TTL)
        if unread_seed == "zero":
            for uid in member_ids:
                pipe.hset(unread_key(uid), room_id, 0)
        await pipe.execute()

        for uid in member_ids:
            await self._fanout.subscribe_user_to_room(uid, room_id)

        for uid in member_ids:
            await self._fanout.fan_out_to_user(
                uid, {"type": "room_joined", "room_id": room_id},
            )

    @transactional
    async def list_user_room_ids(self, user_id: str) -> list[str]:
        """유저가 속한 활성 방 ID 목록. WS 연결 직후 초기 구독에 사용."""
        member_repo = ChatRoomMemberRepository(self._session)
        return await member_repo.find_user_room_ids(user_id)

    async def create_group_room(
        self,
        me_id: str,
        title: str,
        member_ids: list[str],
    ) -> ChatRoomData:
        """그룹 방 생성. creator 포함 초기 멤버. 친구가 아닌 user_id 가 하나라도 있으면 전체 실패.

        Redis 캐시/구독/fan-out/시스템 메시지는 커밋 이후 실행 — 롤백 시 비멤버 잔존 방지.
        """
        room_id, all_member_ids, dto = await self._create_group_room_tx(
            me_id=me_id, title=title, member_ids=member_ids,
        )
        await self._run_side_effect_safe(
            self._emit_room_joined(room_id, all_member_ids, unread_seed="zero"),
            room_id=room_id, label="room_joined:group",
        )
        await self._send_system_message_safe(
            room_id=room_id, action="created", actor_id=me_id,
        )
        logger.info(
            "그룹 방 생성: room_id={}, creator={}, members={}",
            room_id, me_id, all_member_ids,
        )
        return dto

    @transactional
    async def _create_group_room_tx(
        self, *, me_id: str, title: str, member_ids: list[str],
    ) -> tuple[str, list[str], ChatRoomData]:
        """그룹 방 생성 DB 파트 — (room_id, all_member_ids, dto)."""
        targets = {uid for uid in member_ids if uid != me_id}
        if not targets:
            raise ValueError("초대할 대상이 없습니다 (본인 외 멤버 없음).")
        if len(targets) + 1 > MAX_GROUP_MEMBERS:
            raise ValueError(f"그룹 채팅방은 최대 {MAX_GROUP_MEMBERS}명까지 참여할 수 있습니다.")

        friendship_repo = FriendshipRepository(self._session)
        chat_room_repo = ChatRoomRepository(self._session)
        member_repo = ChatRoomMemberRepository(self._session)

        friend_ids = await friendship_repo.find_accepted_friend_ids_with(me_id, targets)
        non_friends = targets - friend_ids
        if non_friends:
            raise ValueError(
                f"친구가 아닌 유저는 초대할 수 없습니다: {sorted(non_friends)}"
            )

        all_member_ids = sorted({me_id, *targets})
        new_room = ChatRoom(
            type=ChatRoomType.GROUP,
            title=title,
            creator_id=me_id,
            direct_user_a_id=None,
            direct_user_b_id=None,
        )
        await chat_room_repo.save(new_room)
        await member_repo.save_all([
            ChatRoomMember(
                chat_room_id=new_room.chat_room_id,
                user_id=uid,
                last_read_message_server_seq=None,
            )
            for uid in all_member_ids
        ])

        return new_room.chat_room_id, all_member_ids, self._to_group_dto(new_room)

    async def _send_system_message_safe(self, **kwargs) -> None:
        """(커밋 후) 시스템 메시지 best-effort 발행 — 실패해도 멤버십 변경은 되돌리지 않는다."""
        try:
            await self._message_service.send_system_message(**kwargs)
        except Exception as e:
            logger.warning(
                "시스템 메시지 발행 실패 (무시): room_id={}, action={}, err={}",
                kwargs.get("room_id"), kwargs.get("action"), type(e).__name__,
            )

    async def _run_side_effect_safe(self, coro, *, room_id: str, label: str) -> None:
        """(커밋 후) Redis/fan-out 부수효과 best-effort — 실패해도 커밋된 멤버십은 안 되돌린다.

        500→재시도로 인한 그룹 방 중복 생성을 막는다. 캐시는 read-repair·TTL 로 DB 기준 수렴.
        """
        try:
            await coro
        except Exception as e:
            logger.warning(
                "채팅 부수효과 실패 (무시): label={}, room_id={}, err={}",
                label, room_id, type(e).__name__,
            )

    async def invite_members(
        self,
        me_id: str,
        room_id: str,
        user_ids: list[str],
    ) -> tuple[list[str], list[str]]:
        """그룹 방에 친구 초대.

        신규 멤버 `last_read = current_seq` (과거 메시지는 읽음 처리).
        재초대 (`is_left=true`) 는 `last_read` 유지 + `notification_muted` 만 리셋.

        Redis 캐시/구독/fan-out/시스템 메시지는 커밋 이후 실행 — 롤백 시 비멤버가 캐시에
        남아 송수신 가능한 상태(최대 TTL)를 방지.
        """
        invited, skipped, new_members, rejoined, _ = await self._invite_members_tx(
            me_id=me_id, room_id=room_id, user_ids=user_ids,
        )
        if not invited:
            return [], skipped

        await self._run_side_effect_safe(
            self._emit_invite_side_effects(
                room_id, invited=invited, new_members=new_members,
                rejoined=rejoined,
            ),
            room_id=room_id, label="invite_side_effects",
        )
        await self._send_system_message_safe(
            room_id=room_id, action="join", actor_id=me_id, target_ids=invited,
        )
        logger.info(
            "멤버 초대: room_id={}, inviter={}, invited={}, skipped={}",
            room_id, me_id, invited, skipped,
        )
        return invited, skipped

    @transactional
    async def _invite_members_tx(
        self,
        *,
        me_id: str,
        room_id: str,
        user_ids: list[str],
    ) -> tuple[list[str], list[str], list[str], list[tuple[str, int]], int]:
        """초대 DB 파트 — (invited, skipped, new_members, rejoined[(uid,last_read)], allocated_seq)."""
        chat_room_repo = ChatRoomRepository(self._session)
        member_repo = ChatRoomMemberRepository(self._session)
        friendship_repo = FriendshipRepository(self._session)
        message_repo = ChatMessageRepository(mongodb.database)

        room = await chat_room_repo.find_by_id(room_id)
        if room is None:
            raise ChatRoomNotFoundError("존재하지 않는 방입니다.")
        if room.type != ChatRoomType.GROUP:
            raise ValueError("그룹 방에만 멤버를 초대할 수 있습니다.")
        if not await member_repo.is_active_member(room_id, me_id):
            raise PermissionError("이 방의 활성 멤버만 초대할 수 있습니다.")

        targets = {uid for uid in user_ids if uid != me_id}
        if not targets:
            raise ValueError("초대할 대상이 없습니다.")

        friend_ids = await friendship_repo.find_accepted_friend_ids_with(me_id, targets)
        non_friends = targets - friend_ids
        if non_friends:
            raise ValueError(
                f"친구가 아닌 유저는 초대할 수 없습니다: {sorted(non_friends)}"
            )

        # 총원을 증가시키는 invite끼리 room row로 직렬화한다. inviter row의 공유 잠금은
        # 대기 중 퇴장·강퇴를 commit 이후로 미뤄 stale 권한 초대를 막는다.
        room = await chat_room_repo.find_by_id_for_update(room_id)
        if room is None:
            raise ChatRoomNotFoundError("존재하지 않는 방입니다.")
        if room.type != ChatRoomType.GROUP:
            raise ValueError("그룹 방에만 멤버를 초대할 수 있습니다.")
        if not await member_repo.is_active_member_for_share(room_id, me_id):
            raise PermissionError("이 방의 활성 멤버만 초대할 수 있습니다.")

        # send와 같은 room mutex 안에서 읽어 가입 이전에 예약된 in-flight seq까지 baseline에
        # 포함한다. lock 밖에서 읽으면 sender commit과 invite commit 사이에 stale해질 수 있다.
        allocated_seq = await self._get_allocated_current_seq(message_repo, room_id)

        skipped: list[str] = []
        candidates: list[tuple[str, ChatRoomMember | None]] = []

        for uid in sorted(targets):
            existing = await member_repo.find(room_id, uid)
            if existing is not None and not existing.is_left:
                skipped.append(uid)
                continue
            candidates.append((uid, existing))

        active_count = await member_repo.count_active_members(room_id)
        if active_count + len(candidates) > MAX_GROUP_MEMBERS:
            raise ValueError(f"그룹 채팅방은 최대 {MAX_GROUP_MEMBERS}명까지 참여할 수 있습니다.")

        invited: list[str] = []
        new_members: list[str] = []
        rejoined: list[tuple[str, int]] = []  # (uid, last_read)
        for uid, existing in candidates:
            if existing is not None and existing.is_left:
                existing.is_left = False
                existing.joined_at = datetime.now(timezone.utc)
                existing.notification_muted = None
                rejoined.append((uid, existing.last_read_message_server_seq or 0))
                invited.append(uid)
            else:
                await member_repo.save(ChatRoomMember(
                    chat_room_id=room_id,
                    user_id=uid,
                    last_read_message_server_seq=allocated_seq or None,
                ))
                new_members.append(uid)
                invited.append(uid)

        return invited, skipped, new_members, rejoined, (allocated_seq or 0)

    async def _emit_invite_side_effects(
        self,
        room_id: str,
        *,
        invited: list[str],
        new_members: list[str],
        rejoined: list[tuple[str, int]],
    ) -> None:
        """(커밋 후) room:members 캐시 무효화 + unread 시드 + 구독 + room_joined fan-out."""
        redis = await get_redis_client()
        message_repo = ChatMessageRepository(mongodb.database)

        # 재초대 unread 는 실제 메시지 수로 시드 — seq 차이는 force_jump/recover 갭 때문에
        # 유령 미읽음을 부풀린다 (recover 경로와 동일 계산).
        rejoin_unread: list[tuple[str, int]] = []
        for uid, last_read in rejoined:
            raw = await message_repo.count_after_seq(
                chat_room_id=room_id, after_seq=last_read, limit=UNREAD_COUNT_LIMIT,
            )
            rejoin_unread.append((uid, min(raw, UNREAD_COUNT_CAP)))

        pipe = redis.pipeline(transaction=True)
        # gen INCR — 초대(멤버십 변경)로 진행 중인 stale read-repair populate 를 무효화.
        pipe.incr(room_members_gen_key(room_id))
        # SADD 부분 갱신 금지 — 키 만료 상태면 초대 멤버만 담긴 부분 집합이 생겨 기존 멤버
        # unread/푸시가 누락된다. 무효화 후 다음 send 의 _ensure_membership 이 DB 로 재적재.
        pipe.delete(room_members_key(room_id))
        for uid, cnt in rejoin_unread:
            pipe.hset(unread_key(uid), room_id, cnt)
        for uid in new_members:
            pipe.hset(unread_key(uid), room_id, 0)
        await pipe.execute()

        for uid in invited:
            await self._fanout.subscribe_user_to_room(uid, room_id)

        for uid in invited:
            await self._fanout.fan_out_to_user(
                uid, {"type": "room_joined", "room_id": room_id},
            )

    async def leave_room(self, me_id: str, room_id: str) -> None:
        """그룹 방 본인 퇴장. 커밋(is_left=True) 후 Redis 정리 — 시스템 메시지 실패가 퇴장을
        되돌리지 않는다. 캐시 부활 방지는 _emit_member_removed 의 gen 가드 참고.
        """
        await self._leave_room_tx(me_id=me_id, room_id=room_id)
        await self._run_side_effect_safe(
            self._emit_member_removed(room_id, me_id),
            room_id=room_id, label="member_removed:leave",
        )
        await self._send_system_message_safe(
            room_id=room_id, action="leave", actor_id=me_id,
        )
        logger.info("그룹 방 퇴장: room_id={}, user_id={}", room_id, me_id)

    @transactional
    async def _leave_room_tx(self, *, me_id: str, room_id: str) -> None:
        """퇴장 DB 파트 — 방/멤버 검증 후 is_left=True."""
        chat_room_repo = ChatRoomRepository(self._session)
        member_repo = ChatRoomMemberRepository(self._session)

        room = await chat_room_repo.find_by_id(room_id)
        if room is None:
            raise ChatRoomNotFoundError("존재하지 않는 방입니다.")
        if room.type != ChatRoomType.GROUP:
            raise ValueError("그룹 방만 퇴장할 수 있습니다.")

        member = await member_repo.find(room_id, me_id)
        if member is None or member.is_left:
            raise PermissionError("이 방의 활성 멤버가 아닙니다.")

        member.is_left = True
        await member_repo.update(member)

    async def _emit_member_removed(self, room_id: str, user_id: str) -> None:
        """(커밋 후) 멤버 제거 부수효과 — SREM + unread HDEL + room_left fan-out + 구독 해제.

        구독 해제를 시스템 메시지보다 먼저 — 당사자가 자기 퇴장/강퇴 메시지를 받지 않도록.
        """
        redis = await get_redis_client()
        pipe = redis.pipeline(transaction=True)
        # gen INCR + SREM 을 한 MULTI 로 원자 실행 — stale read-repair populate 가 gen 불일치로
        # skip 되어 제거된 멤버가 캐시에 부활하지 않는다 (상세 불변식은 populate_members.lua).
        pipe.incr(room_members_gen_key(room_id))
        pipe.srem(room_members_key(room_id), user_id)
        pipe.hdel(unread_key(user_id), room_id)
        await pipe.execute()

        await self._fanout.fan_out_to_user(
            user_id, {"type": "room_left", "room_id": room_id},
        )
        await self._fanout.unsubscribe_user_from_room(user_id, room_id)

    async def kick_member(
        self, me_id: str, room_id: str, target_user_id: str,
    ) -> None:
        """그룹 방 강퇴 — creator 전용. 커밋 이후 캐시/구독/시스템 메시지 정리."""
        await self._kick_member_tx(
            me_id=me_id, room_id=room_id, target_user_id=target_user_id,
        )
        await self._run_side_effect_safe(
            self._emit_member_removed(room_id, target_user_id),
            room_id=room_id, label="member_removed:kick",
        )
        await self._send_system_message_safe(
            room_id=room_id, action="kick", actor_id=me_id, target_ids=[target_user_id],
        )
        logger.info(
            "멤버 강퇴: room_id={}, kicker={}, target={}",
            room_id, me_id, target_user_id,
        )

    @transactional
    async def _kick_member_tx(
        self, *, me_id: str, room_id: str, target_user_id: str,
    ) -> None:
        """강퇴 DB 파트 — creator 권한 검증 후 대상 is_left=True."""
        if me_id == target_user_id:
            raise ValueError("자기 자신은 강퇴할 수 없습니다. 퇴장 API 를 사용하세요.")

        chat_room_repo = ChatRoomRepository(self._session)
        member_repo = ChatRoomMemberRepository(self._session)

        room = await chat_room_repo.find_by_id(room_id)
        if room is None:
            raise ChatRoomNotFoundError("존재하지 않는 방입니다.")
        if room.type != ChatRoomType.GROUP:
            raise ValueError("그룹 방에서만 강퇴할 수 있습니다.")
        if room.creator_id != me_id:
            raise PermissionError("방장만 강퇴할 수 있습니다.")
        if not await member_repo.is_active_member(room_id, me_id):
            raise PermissionError("방장이 이미 방을 떠난 상태입니다.")

        target = await member_repo.find(room_id, target_user_id)
        if target is None or target.is_left:
            raise ValueError("강퇴 대상이 활성 멤버가 아닙니다.")

        target.is_left = True
        await member_repo.update(target)

    async def mark_read(
        self,
        *,
        me_id: str,
        me_session_id: str,
        room_id: str,
        up_to_server_seq: int,
    ) -> int:
        """읽음 포인터 commit 후 unread 재계산 + fan-out. regress 는 DB GREATEST 가 차단.

        탈퇴자의 read 요청은 PermissionError. 반환값은 최종 반영된 seq.
        """
        if up_to_server_seq <= 0:
            raise ValueError("up_to_server_seq 는 1 이상이어야 합니다.")

        redis = await get_redis_client()
        expected_generation = int(
            await redis.get(room_members_gen_key(room_id)) or 0
        )
        final_seq, clamped_seq = await self._mark_read_tx(
            me_id=me_id,
            room_id=room_id,
            up_to_server_seq=up_to_server_seq,
        )
        sync_status, effective_seq = await self._sync_unread_under_room_lock(
            me_id=me_id,
            room_id=room_id,
            final_seq=final_seq,
            expected_generation=expected_generation,
        )

        if int(sync_status) == 3:
            raise RuntimeError("읽음 처리 중 방 멤버십이 변경되었습니다. 다시 시도해주세요.")
        if int(sync_status) == 0:
            logger.info(
                "늦은 읽음 fanout 승격: room_id={}, user_id={}, seq={}, applied_seq={}",
                room_id, me_id, final_seq, effective_seq,
            )
            # 높은 요청의 publish 실패도 낮은 요청이 보완하도록 단조 seq로 fanout한다.
            final_seq = int(effective_seq)

        await self._fanout.fan_out_to_room(
            room_id,
            {
                "type": "read",
                "user_id": me_id,
                "sender_session_id": me_session_id,
                "up_to_server_seq": final_seq,
            },
        )

        logger.info(
            "읽음 마킹: room_id={}, user_id={}, up_to_seq={}, final_seq={}",
            room_id, me_id, clamped_seq, final_seq,
        )
        return final_seq

    async def _sync_unread_under_room_lock(
        self,
        *,
        me_id: str,
        room_id: str,
        final_seq: int,
        expected_generation: int,
    ) -> tuple[int, int]:
        """send와 room X-lock으로 직렬화해 residual과 Redis delta의 경계를 고정한다."""
        async with self.uow.session_factory() as session:
            room_repo = ChatRoomRepository(session)
            if await room_repo.find_by_id_for_update(room_id) is None:
                raise ChatRoomNotFoundError("존재하지 않는 방입니다.")

            redis = await get_redis_client()
            unread_k = unread_key(me_id)
            baseline = int(await redis.hget(unread_k, room_id) or 0)
            residual = await ChatMessageRepository(mongodb.database).count_after_seq(
                chat_room_id=room_id,
                after_seq=final_seq,
                limit=UNREAD_COUNT_LIMIT,
            )
            _, sync_status, effective_seq = await lua_scripts.mark_read_unread(
                keys=[unread_k, read_sync_key(me_id), room_members_gen_key(room_id)],
                args=[
                    room_id, residual, baseline, UNREAD_COUNT_CAP, final_seq, 0,
                    expected_generation,
                ],
            )
            return int(sync_status), int(effective_seq)

    @transactional
    async def _mark_read_tx(
        self,
        *,
        me_id: str,
        room_id: str,
        up_to_server_seq: int,
    ) -> tuple[int, int]:
        """읽음 포인터 DB 갱신 — 외부 부수효과는 호출자가 commit 이후 수행."""
        chat_room_repo = ChatRoomRepository(self._session)
        member_repo = ChatRoomMemberRepository(self._session)

        room = await chat_room_repo.find_by_id(room_id)
        if room is None:
            raise ChatRoomNotFoundError("존재하지 않는 방입니다.")

        # Redis seq는 Mongo insert 전에 예약되므로 읽음 상한으로 쓸 수 없다. 클라가 큰 값을
        # 보내도 내구 저장된 최대 seq까지만 반영해 in-flight 메시지의 선행 읽음을 막는다.
        message_repo = ChatMessageRepository(mongodb.database)
        durable_seq = await self._get_durable_current_seq(message_repo, room_id)
        clamped_seq = min(up_to_server_seq, durable_seq)

        final_seq = await member_repo.mark_read(room_id, me_id, clamped_seq)
        if final_seq is None:
            raise PermissionError("이 방의 활성 멤버가 아닙니다.")
        return final_seq, clamped_seq

    @staticmethod
    async def _get_durable_current_seq(
        message_repo: ChatMessageRepository,
        room_id: str,
    ) -> int:
        """Mongo에 내구 저장된 방의 최대 server_seq. 메시지가 없으면 0."""
        return await message_repo.get_max_server_seq(room_id)

    @staticmethod
    async def _get_allocated_current_seq(
        message_repo: ChatMessageRepository,
        room_id: str,
    ) -> int:
        """초대 baseline용 Redis 예약 seq. cache miss/손상 시 Mongo max로 복구."""
        redis = await get_redis_client()
        raw = await redis.get(room_seq_key(room_id))
        if raw is not None:
            try:
                return int(raw)
            except ValueError:
                pass
        return await message_repo.get_max_server_seq(room_id)

    @staticmethod
    def _to_group_dto(room: ChatRoom) -> ChatRoomData:
        """그룹 방 생성 직후 DTO — peer / last_message 모두 None."""
        return ChatRoomData(
            chat_room_id=room.chat_room_id,
            type=room.type,
            title=room.title,
            peer=None,
            last_message=None,
            unread_count=0,
            last_message_at=room.last_message_at,
            effective_last_at=room.effective_last_at or room.created_at,
            notification_muted=False,
        )

    @staticmethod
    async def _to_dto(room: ChatRoom, me_id: str, peer) -> ChatRoomData:
        """1:1 방 DTO 변환. 신규 / 재활용 모두 last_message 는 None, mute 는 False 로 응답.

        정확한 mute 상태는 클라가 list/get 으로 다시 받는다.
        """
        peer_dto = ChatRoomPeerData(
            user_id=peer.user_id,
            user_name=peer.detail.user_name if peer.detail else None,
            profile_image_url=peer.detail.profile_image_url if peer.detail else None,
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
            notification_muted=False,
        )
