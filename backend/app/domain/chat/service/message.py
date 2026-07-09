"""메시지 송신 / 편집 / 삭제 서비스."""
import asyncio
import json
import random
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

from app.core.chat.lua_script import lua_scripts
from app.core.chat.redis_key import (
    DEDUPE_TTL,
    DIRTY_CHAT_ROOM_KEY,
    RATE_LIMIT_THRESHOLD,
    RATE_LIMIT_TTL,
    ROOM_BLOCKS_TTL,
    ROOM_MEMBERS_TTL,
    SEQ_FORCE_JUMP_GAP,
    SEQ_FORCE_JUMP_JITTER_MAX,
    SEQ_RECOVER_GAP,
    dedupe_key,
    rate_msg_key,
    room_blocks_key,
    room_members_gen_key,
    room_members_key,
    room_seq_key,
    unread_key,
)
from app.core.logger import get_logger
from app.core.redis import get_redis_client, get_redis_dedupe_client
from app.database.session import UnitOfWork, _current_session, mongodb, transactional
from app.domain.chat.dto.message import MessageSentAckData
from app.domain.chat.model.chat_message import MessageType
from app.domain.chat.model.chat_room import ChatRoom, ChatRoomType
from app.domain.chat.repository.chat_member import ChatRoomMemberRepository
from app.domain.chat.repository.chat_message import ChatMessageRepository
from app.domain.chat.repository.chat_room import ChatRoomRepository
from app.domain.chat.service.exception import UpstreamError
from app.domain.friend.repository.user_block import UserBlockRepository
from app.util.id_generator import generate_message_id


logger = get_logger("chat.send")


_MAX_INSERT_ATTEMPTS = 3
EDIT_TIME_LIMIT = timedelta(minutes=5)
_PUSH_BODY_PREVIEW_LIMIT = 100

# dedupe 값의 예약(placeholder) 상태 — Mongo durable 후 ACK JSON 으로 교체된다.
_DEDUPE_PENDING = "1"

# fire-and-forget task 핸들 보관 — GC 가 미참조 task 를 회수하지 않도록.
_PUSH_TASKS: set[asyncio.Task] = set()


class MessageService:
    """메시지 송신 핫패스."""

    def __init__(self, uow: UnitOfWork, fanout_service, fcm_service_factory):
        self.uow = uow
        self._fanout = fanout_service
        self._fcm_factory = fcm_service_factory

    @transactional
    async def send_message(
        self,
        *,
        sender_user_id: str,
        sender_session_id: str,
        room_id: str,
        client_msg_id: str,
        msg_type: MessageType,
        content: str,
    ) -> MessageSentAckData:
        """WS `op=send` 처리 — ACK DTO 반환, 실패는 예외로 전파."""

        member_repo = ChatRoomMemberRepository(self._session)
        chat_room_repo = ChatRoomRepository(self._session)
        message_repo = ChatMessageRepository(mongodb.database)
        block_repo = UserBlockRepository(self._session)

        redis_hot = await get_redis_client()
        redis_dedupe = await get_redis_dedupe_client()

        await self._ensure_membership(
            redis_hot, member_repo, room_id=room_id, user_id=sender_user_id,
        )

        count = await lua_scripts.incr_with_ttl(
            keys=[rate_msg_key(sender_user_id)],
            args=[RATE_LIMIT_TTL],
        )
        if count > RATE_LIMIT_THRESHOLD:
            raise ValueError("메시지 전송 속도 제한에 걸렸습니다. 잠시 후 다시 시도해주세요.")

        # 차단 체크는 DIRECT 방만 — GROUP 은 차단과 송신이 독립.
        room = await chat_room_repo.find_by_id(room_id)
        if room is None:
            raise ValueError("존재하지 않는 방입니다.")
        if room.type == ChatRoomType.DIRECT:
            if await self._is_direct_blocked(
                redis_hot, block_repo, room=room, sender_user_id=sender_user_id,
            ):
                raise PermissionError(
                    "차단 관계인 유저에게는 메시지를 보낼 수 없습니다.",
                )

        # dedupe — NX 선점. placeholder 로 예약 후 Mongo durable 되면 값에 ACK 를 기록한다.
        # 재전송(hit): 값이 ACK 면 원본 ACK 를 replay(전송은 성공했으나 ACK 프레임을 잃은 클라
        # 구제), 아직 placeholder 면 최초 전송이 in-flight → 재시도 유도.
        dedupe_k = dedupe_key(sender_user_id, client_msg_id)
        first_time = await redis_dedupe.set(dedupe_k, _DEDUPE_PENDING, nx=True, ex=DEDUPE_TTL)
        if not first_time:
            replay = await self._replay_ack_if_available(
                redis_dedupe, dedupe_k, client_msg_id,
            )
            if replay is not None:
                return replay
            raise ValueError("메시지가 처리 중입니다. 잠시 후 다시 시도해주세요.")

        # Mongo 저장 성공이 dedupe 유지의 경계 — 이 블록에서 어떤 예외든 dedupe 를 풀어
        # 클라가 같은 client_msg_id 로 재시도 가능하게 한다.
        try:
            server_seq = await self._allocate_seq(
                message_repo, redis_hot, room_id=room_id,
            )

            now = datetime.now(timezone.utc)
            message_id = generate_message_id()
            doc = {
                "_id": message_id,
                "chat_room_id": room_id,
                "server_seq": server_seq,
                "sender_id": sender_user_id,
                "type": msg_type.value,
                "content": content,
                "created_at": now,
                "edited_at": None,
                "deleted_at": None,
            }

            for attempt in range(_MAX_INSERT_ATTEMPTS):
                try:
                    await message_repo.insert(doc)
                    break
                except DuplicateKeyError:
                    jitter = random.randint(1, SEQ_FORCE_JUMP_JITTER_MAX)
                    new_seq = await lua_scripts.force_jump(
                        keys=[room_seq_key(room_id)],
                        args=[SEQ_FORCE_JUMP_GAP, jitter],
                    )
                    server_seq = int(new_seq)
                    doc["server_seq"] = server_seq
            else:
                logger.error(
                    "메시지 저장 {}회 연속 DuplicateKey: room_id={}, user_id={}",
                    _MAX_INSERT_ATTEMPTS, room_id, sender_user_id,
                )
                raise UpstreamError("메시지 저장에 실패했습니다. 잠시 후 다시 시도해주세요.")

        except Exception:
            await redis_dedupe.delete(dedupe_k)
            raise

        # Mongo durable 확정 — dedupe 값에 ACK 를 기록해 재전송 시 replay 가능하게 한다.
        # best-effort (실패 시 재전송은 placeholder 를 보고 재시도 유도 — 잘못된 결과는 없다).
        await self._record_dedupe_ack(
            redis_dedupe, dedupe_k,
            room_id=room_id, message_id=message_id, server_seq=server_seq, at=now,
        )

        # last_message 는 바깥 트랜잭션 SAVEPOINT 로 갱신 — 커넥션 1개 (별도 세션은 송신당
        # C1+C2 동시 점유로 공유 풀 데드락). if_greater 가드로 동시 송신 seq regress 방지,
        # 실패는 dirty 큐 → reconcile 이 Mongo 기준 수렴.
        try:
            async with self._session.begin_nested():
                await chat_room_repo.update_last_message_if_greater(
                    chat_room_id=room_id,
                    message_id=message_id,
                    server_seq=server_seq,
                    at=now,
                )
        except Exception as e:
            logger.warning(
                "last_message_* 갱신 실패 → dirty 큐 적재: room_id={}, err={}",
                room_id, type(e).__name__,
            )
            await redis_hot.sadd(DIRTY_CHAT_ROOM_KEY, room_id)

        # 여기 도달 = Mongo durable 저장 완료 = 송신 성공 확정. 이후 unread/fanout 은 best-effort —
        # 예외 전파하면 클라가 저장된 메시지에 에러 ACK 를 받고(dedupe 로 재전송도 거절 → 영구 실패),
        # @transactional rollback 으로 last_message 까지 유실된다.
        if msg_type != MessageType.SYSTEM:
            try:
                await self._bump_unread(redis_hot, room_id=room_id, sender_user_id=sender_user_id)
            except Exception as e:
                logger.warning(
                    "unread 증가 실패 (메시지는 저장됨): room_id={}, err={}",
                    room_id, type(e).__name__,
                )

        try:
            await self._fanout.fan_out_to_room(
                room_id,
                {
                    "type": "message.new",
                    "sender_session_id": sender_session_id,
                    "message": {
                        "message_id": message_id,
                        "chat_room_id": room_id,
                        "server_seq": server_seq,
                        "sender_id": sender_user_id,
                        "type": msg_type.value,
                        "content": content,
                        "created_at": now.isoformat(),
                    },
                },
            )
        except Exception as e:
            logger.warning(
                "fanout 실패 (메시지는 저장됨 — 수신자는 히스토리/FCM 으로 수신): "
                "room_id={}, err={}",
                room_id, type(e).__name__,
            )

        # FCM 푸시는 fire-and-forget — ACK 지연 차단. 트랜잭션 밖이지만 fanout 까지 도달한
        # 시점에 메시지는 사실상 "출시" 상태라 후속 롤백 없음.
        if msg_type != MessageType.SYSTEM:
            self._spawn_push_task(
                room_id=room_id,
                sender_user_id=sender_user_id,
                content=content,
            )

        return MessageSentAckData(
            client_msg_id=client_msg_id,
            message_id=message_id,
            server_seq=server_seq,
            created_at=now,
        )

    @staticmethod
    async def _ensure_membership(
        redis_hot,
        member_repo: ChatRoomMemberRepository,
        *,
        room_id: str,
        user_id: str,
    ) -> None:
        """`room:members:{R}` 캐시로 멤버십 검증. miss 시 방 멤버 전체를 RDB 로드 후 SADD."""
        key = room_members_key(room_id)
        is_member = await redis_hot.sismember(key, user_id)
        if is_member:
            # 슬라이딩 TTL — 후속 _bump_unread/FCM 이 같은 키를 smembers 하기 전 TTL 이 만료되면
            # 빈 집합 → unread·푸시 누락. 접근 시마다 연장해 사용 도중 만료를 막는다.
            await redis_hot.expire(key, ROOM_MEMBERS_TTL)
            return

        # generation 을 DB 읽기 "직전" 에 캡처한다. 이 사이 leave/kick 이 커밋되면 gen 이 바뀌어
        # populate_members.lua 가 SADD 를 건너뛰므로, 제거된 멤버가 부활하지 않는다.
        gen_key = room_members_gen_key(room_id)
        gen0 = await redis_hot.get(gen_key) or "0"

        members = await member_repo.find_active_member_ids(room_id)
        if not members:
            raise ValueError("존재하지 않는 방이거나 멤버가 없습니다.")

        # gen 이 그대로일 때만 캐시 반영. skip(0) 이어도 다음 send 가 재적재하므로 안전.
        await lua_scripts.populate_members(
            keys=[key, gen_key],
            args=[gen0, ROOM_MEMBERS_TTL, *members],
        )

        if user_id not in members:
            raise PermissionError("이 방의 멤버가 아닙니다.")

    @staticmethod
    async def _allocate_seq(
        message_repo: ChatMessageRepository,
        redis_hot,
        *,
        room_id: str,
    ) -> int:
        """핫: `incr_fast.lua`. 키 부재 시 Mongo `max(server_seq)` + `SEQ_RECOVER_GAP` 로 복구."""
        seq = await lua_scripts.incr_fast(keys=[room_seq_key(room_id)])
        seq = int(seq)
        if seq != -1:
            return seq

        mongo_max = await message_repo.get_max_server_seq(room_id)
        base = mongo_max + SEQ_RECOVER_GAP if mongo_max > 0 else 0
        recovered = await lua_scripts.recover_and_incr(
            keys=[room_seq_key(room_id)],
            args=[base],
        )
        return int(recovered)

    @staticmethod
    async def _record_dedupe_ack(
        redis_dedupe, dedupe_k: str, *,
        room_id: str, message_id: str, server_seq: int, at: datetime,
    ) -> None:
        """dedupe 값을 ACK JSON 으로 교체 (KEEPTTL 로 예약 시 만료 유지). 실패는 무시."""
        try:
            await redis_dedupe.set(
                dedupe_k,
                json.dumps({
                    "message_id": message_id,
                    "server_seq": server_seq,
                    "created_at": at.isoformat(),
                }),
                keepttl=True,
            )
        except Exception as e:
            logger.warning(
                "dedupe ACK 기록 실패 (무시): room_id={}, err={}",
                room_id, type(e).__name__,
            )

    @staticmethod
    async def _replay_ack_if_available(
        redis_dedupe, dedupe_k: str, client_msg_id: str,
    ) -> MessageSentAckData | None:
        """dedupe 값에 기록된 ACK 를 복원. placeholder/파싱 실패면 None."""
        raw = await redis_dedupe.get(dedupe_k)
        if not raw or raw == _DEDUPE_PENDING:
            return None
        try:
            data = json.loads(raw)
            return MessageSentAckData(
                client_msg_id=client_msg_id,
                message_id=data["message_id"],
                server_seq=int(data["server_seq"]),
                created_at=datetime.fromisoformat(data["created_at"]),
            )
        except (ValueError, TypeError, KeyError):
            return None

    @transactional
    async def send_system_message(
        self,
        *,
        room_id: str,
        action: str,
        actor_id: str | None,
        target_ids: list[str] | None = None,
        actor_session_id: str | None = None,
    ) -> None:
        """방 관리 액션 (`created`/`join`/`leave`/`kick`) 의 타임라인 시스템 메시지 기록.

        멤버십 / rate limit / dedupe / unread 증가 모두 skip.
        `actor_session_id` 가 있으면 해당 세션 자기 에코를 차단.
        """
        message_repo = ChatMessageRepository(mongodb.database)
        chat_room_repo = ChatRoomRepository(self._session)
        redis_hot = await get_redis_client()

        server_seq = await self._allocate_seq(
            message_repo, redis_hot, room_id=room_id,
        )

        now = datetime.now(timezone.utc)
        message_id = generate_message_id()
        content: dict = {"action": action, "actor_id": actor_id}
        if target_ids:
            content["target_ids"] = list(target_ids)

        doc = {
            "_id": message_id,
            "chat_room_id": room_id,
            "server_seq": server_seq,
            "sender_id": None,
            "type": MessageType.SYSTEM.value,
            "content": content,
            "created_at": now,
            "edited_at": None,
            "deleted_at": None,
        }

        for attempt in range(_MAX_INSERT_ATTEMPTS):
            try:
                await message_repo.insert(doc)
                break
            except DuplicateKeyError:
                jitter = random.randint(1, SEQ_FORCE_JUMP_JITTER_MAX)
                new_seq = await lua_scripts.force_jump(
                    keys=[room_seq_key(room_id)],
                    args=[SEQ_FORCE_JUMP_GAP, jitter],
                )
                server_seq = int(new_seq)
                doc["server_seq"] = server_seq
        else:
            logger.error(
                "시스템 메시지 {}회 연속 실패: room_id={}, action={}",
                _MAX_INSERT_ATTEMPTS, room_id, action,
            )
            raise UpstreamError("시스템 메시지 저장에 실패했습니다.")

        # last_message_* 갱신은 SAVEPOINT 로 (커넥션 1개). if_greater 가드로 유저 메시지와
        # 엇갈려 커밋돼도 낮은 seq 가 높은 seq 를 덮어써 regress 하지 않는다 (일반 송신과 동일).
        try:
            async with self._session.begin_nested():
                await chat_room_repo.update_last_message_if_greater(
                    chat_room_id=room_id,
                    message_id=message_id,
                    server_seq=server_seq,
                    at=now,
                )
        except Exception as e:
            logger.warning(
                "시스템 메시지 last_message_* 갱신 실패 → dirty 큐: room_id={}, err={}",
                room_id, type(e).__name__,
            )
            await redis_hot.sadd(DIRTY_CHAT_ROOM_KEY, room_id)

        # fanout 은 best-effort — Redis 장애로 예외가 나도 이미 durable 한 시스템 메시지를
        # 롤백/실패시키지 않는다 (수신자는 히스토리로 수신, 일반 송신 경로와 동일).
        try:
            await self._fanout.fan_out_to_room(
                room_id,
                {
                    "type": "message.new",
                    "sender_session_id": actor_session_id,
                    "message": {
                        "message_id": message_id,
                        "chat_room_id": room_id,
                        "server_seq": server_seq,
                        "sender_id": None,
                        "type": MessageType.SYSTEM.value,
                        "content": content,
                        "created_at": now.isoformat(),
                    },
                },
            )
        except Exception as e:
            logger.warning(
                "시스템 메시지 fanout 실패 (메시지는 저장됨): room_id={}, err={}",
                room_id, type(e).__name__,
            )

        logger.info(
            "시스템 메시지: room_id={}, action={}, actor={}, seq={}, target_ids={}",
            room_id, action, actor_id, server_seq, target_ids,
        )

    @transactional
    async def edit_message(
        self,
        *,
        message_id: str,
        editor_user_id: str,
        editor_session_id: str,
        new_content: str,
    ) -> dict:
        """본인 메시지를 5분 이내 편집. 시스템 메시지 / 삭제된 메시지 / 비활성 멤버는 거절."""
        member_repo = ChatRoomMemberRepository(self._session)
        message_repo = ChatMessageRepository(mongodb.database)

        doc = await message_repo.find_by_id(message_id)
        if doc is None:
            raise ValueError("존재하지 않는 메시지입니다.")
        if doc.get("deleted_at") is not None:
            raise ValueError("삭제된 메시지는 편집할 수 없습니다.")
        if doc.get("type") == MessageType.SYSTEM.value:
            raise PermissionError("시스템 메시지는 편집할 수 없습니다.")
        if doc.get("sender_id") != editor_user_id:
            raise PermissionError("본인 메시지만 편집할 수 있습니다.")

        room_id = doc["chat_room_id"]
        if not await member_repo.is_active_member(room_id, editor_user_id):
            raise PermissionError("이 방의 활성 멤버가 아닙니다.")

        now = datetime.now(timezone.utc)
        created_at = doc["created_at"]
        if (now - created_at) > EDIT_TIME_LIMIT:
            raise ValueError("메시지 편집 제한 시간(5분)이 지났습니다.")

        await message_repo.update_content(
            message_id, new_content, edited_at=now,
        )

        await self._fanout.fan_out_to_room(
            room_id,
            {
                "type": "message.updated",
                "sender_session_id": editor_session_id,
                "message_id": message_id,
                "content": new_content,
                "edited_at": now.isoformat(),
            },
        )

        logger.info(
            "메시지 편집: message_id={}, editor={}, room_id={}",
            message_id, editor_user_id, room_id,
        )
        return {"message_id": message_id, "content": new_content, "edited_at": now}

    @transactional
    async def delete_message(
        self,
        *,
        message_id: str,
        deleter_user_id: str,
        deleter_session_id: str,
    ) -> None:
        """본인 메시지 또는 그룹방 creator 의 soft delete.

        탈퇴한 creator 는 권한 소멸 — 현재 활성 멤버여야만 유효.
        시스템 메시지는 삭제 불가.
        """
        member_repo = ChatRoomMemberRepository(self._session)
        chat_room_repo = ChatRoomRepository(self._session)
        message_repo = ChatMessageRepository(mongodb.database)

        doc = await message_repo.find_by_id(message_id)
        if doc is None:
            raise ValueError("존재하지 않는 메시지입니다.")
        if doc.get("deleted_at") is not None:
            raise ValueError("이미 삭제된 메시지입니다.")
        if doc.get("type") == MessageType.SYSTEM.value:
            raise PermissionError("시스템 메시지는 삭제할 수 없습니다.")

        room_id = doc["chat_room_id"]
        sender_id = doc.get("sender_id")

        if not await member_repo.is_active_member(room_id, deleter_user_id):
            raise PermissionError("이 방의 활성 멤버가 아닙니다.")

        if sender_id != deleter_user_id:
            room = await chat_room_repo.find_by_id(room_id)
            if room is None:
                raise ValueError("존재하지 않는 방입니다.")
            is_group_creator = (
                room.type == ChatRoomType.GROUP
                and room.creator_id == deleter_user_id
            )
            if not is_group_creator:
                raise PermissionError(
                    "본인 메시지 또는 그룹 방장만 삭제할 수 있습니다.",
                )

        now = datetime.now(timezone.utc)
        await message_repo.soft_delete(message_id, deleted_at=now)

        await self._fanout.fan_out_to_room(
            room_id,
            {
                "type": "message.deleted",
                "sender_session_id": deleter_session_id,
                "message_id": message_id,
                "deleted_at": now.isoformat(),
            },
        )

        logger.info(
            "메시지 삭제: message_id={}, deleter={}, room_id={}, was_own={}",
            message_id, deleter_user_id, room_id, sender_id == deleter_user_id,
        )

    @staticmethod
    async def _is_direct_blocked(
        redis_hot,
        block_repo: UserBlockRepository,
        *,
        room: ChatRoom,
        sender_user_id: str,
    ) -> bool:
        """1:1 방에서 양방향 차단 체크 — 한쪽이라도 차단이면 True.

        캐시 miss 시 양방향 `user_block` 조회 후 SADD. 차단 0 건이어도 `__none__` sentinel
        로 key 를 존재시켜 miss vs empty 를 구분한다.
        """
        peer_id = (
            room.direct_user_b_id
            if room.direct_user_a_id == sender_user_id
            else room.direct_user_a_id
        )
        if peer_id is None:
            return False

        key = room_blocks_key(room.chat_room_id)
        if not await redis_hot.exists(key):
            blocks = await block_repo.find_blocks_between(sender_user_id, peer_id)
            members = (
                [f"{b.blocker_id}:{b.blocked_id}" for b in blocks] or ["__none__"]
            )
            pipe = redis_hot.pipeline(transaction=True)
            pipe.sadd(key, *members)
            pipe.expire(key, ROOM_BLOCKS_TTL)
            await pipe.execute()

        if await redis_hot.sismember(key, f"{sender_user_id}:{peer_id}"):
            return True
        if await redis_hot.sismember(key, f"{peer_id}:{sender_user_id}"):
            return True
        return False

    @staticmethod
    async def _bump_unread(redis_hot, *, room_id: str, sender_user_id: str) -> None:
        """방 멤버 (발신자 제외) unread HINCRBY 를 pipeline 1 RTT 로.

        `transaction=False` — 100명 방에서도 Redis single-thread 가 블로킹되지 않게.
        실패는 무시 (reconcile 경로로 수렴).
        """
        key = room_members_key(room_id)
        members = await redis_hot.smembers(key)
        recipients = [uid for uid in members if uid != sender_user_id]
        if not recipients:
            return

        pipe = redis_hot.pipeline(transaction=False)
        for uid in recipients:
            pipe.hincrby(unread_key(uid), room_id, 1)
        try:
            await pipe.execute()
        except Exception as e:
            logger.warning(
                "unread pipeline 실패 (무시하고 진행): room_id={}, err={}",
                room_id, type(e).__name__,
            )

    def _spawn_push_task(
        self, *, room_id: str, sender_user_id: str, content: str,
    ) -> None:
        """푸시 task 를 백그라운드로 spawn. 모듈 set 에 핸들 보관해 GC 회수 방지."""
        task = asyncio.create_task(
            self._push_chat_to_recipients(
                room_id=room_id,
                sender_user_id=sender_user_id,
                content=content,
            )
        )
        _PUSH_TASKS.add(task)
        task.add_done_callback(_PUSH_TASKS.discard)

    async def _push_chat_to_recipients(
        self, *, room_id: str, sender_user_id: str, content: str,
    ) -> None:
        """발신자 제외 방 멤버 전체에 FCM 푸시. 어떤 예외도 raise 하지 않는다."""
        # 상속된 부모 Context 엔 이미 닫힌 세션이 박혀있다 — 끊어줘야 하위 @transactional 이
        # 좀비 세션에 join 하지 않고 새 트랜잭션을 연다.
        _current_session.set(None)
        # fire-and-forget 이라 동시 실행될 수 있어 task 마다 새 FcmService(독립 세션)를 만든다.
        # 공유하면 인스턴스 상태(self._session)가 task 간 덮어써진다.
        fcm = self._fcm_factory()
        try:
            redis_hot = await get_redis_client()
            members = await redis_hot.smembers(room_members_key(room_id))
            recipients = [uid for uid in members if uid != sender_user_id]
            if not recipients:
                return

            body = (
                content[:_PUSH_BODY_PREVIEW_LIMIT] + "..."
                if len(content) > _PUSH_BODY_PREVIEW_LIMIT
                else content
            )

            # title 은 FcmService 가 sender_id 로 user_name 조회해 채움 (결손 시 "새 메시지" 폴백).
            await fcm.send_chat_push(
                user_ids=recipients,
                chat_room_id=room_id,
                sender_id=sender_user_id,
                body=body,
            )
        except Exception as e:
            logger.warning(
                "FCM 푸시 helper 실패 (무시): room_id={}, err={}",
                room_id, type(e).__name__,
            )
