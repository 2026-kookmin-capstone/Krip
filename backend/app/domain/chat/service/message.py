"""메시지 송신 / 편집 / 삭제 서비스."""
import asyncio
import json
import random
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import cast

from bson import json_util
from pymongo.errors import ConnectionFailure, DuplicateKeyError, PyMongoError

from app.core.background_tasks import background_tasks
from app.core.chat.lua_script import lua_scripts
from app.core.chat.redis_key import (
    DEDUPE_TTL,
    DIRTY_CHAT_ROOM_KEY,
    RATE_LIMIT_THRESHOLD,
    RATE_LIMIT_TTL,
    ROOM_MEMBERS_TTL,
    SEQ_FORCE_JUMP_GAP,
    SEQ_FORCE_JUMP_JITTER_MAX,
    SEQ_RECOVER_GAP,
    dedupe_key,
    rate_msg_key,
    room_members_gen_key,
    room_members_key,
    room_pending_message_key,
    room_seq_key,
    unread_key,
    unread_watermark_key,
)
from app.core.logger import get_logger
from app.core.redis import get_redis_client, get_redis_dedupe_client
from app.database.session import UnitOfWork, _current_session, mongodb, transactional
from app.domain.chat.dto.message import MessageSentAckData
from app.domain.chat.model.chat_message import MessageType
from app.domain.chat.model.chat_room import ChatRoomType
from app.domain.chat.repository.chat_member import ChatRoomMemberRepository
from app.domain.chat.repository.chat_message import ChatMessageRepository
from app.domain.chat.repository.chat_room import ChatRoomRepository
from app.domain.chat.service.exception import (
    PendingRecoveryDeferred,
    UpstreamError,
)
from app.domain.friend.repository.user_block import UserBlockRepository
from app.util.id_generator import generate_message_id


logger = get_logger("chat.send")


_MAX_INSERT_ATTEMPTS = 3
FOREGROUND_MONGO_RETRY_SEC = 15.0
EDIT_TIME_LIMIT = timedelta(minutes=5)
_PUSH_BODY_PREVIEW_LIMIT = 100

# dedupe 값의 예약(placeholder) 상태 — Mongo durable 후 ACK JSON 으로 교체된다.
_DEDUPE_PENDING = "1"

_DEFERRED_INSERT_CANCEL: ContextVar[bool] = ContextVar(
    "chat_deferred_insert_cancel", default=False,
)
_CALLER_INSERT_CANCEL: ContextVar[bool] = ContextVar(
    "chat_caller_insert_cancel", default=False,
)
_MONGO_RECOVERY_DEADLINE: ContextVar[float | None] = ContextVar(
    "chat_mongo_recovery_deadline", default=None,
)
_DEFER_PENDING_RECOVERY_CANCEL: ContextVar[bool] = ContextVar(
    "chat_defer_pending_recovery_cancel", default=True,
)


class _AwaitableCancelled(Exception):
    pass


def _with_mongo_recovery_deadline(fn):
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        if _MONGO_RECOVERY_DEADLINE.get() is not None:
            return await fn(*args, **kwargs)
        deadline = asyncio.get_running_loop().time() + FOREGROUND_MONGO_RETRY_SEC
        token = _MONGO_RECOVERY_DEADLINE.set(deadline)
        try:
            return await fn(*args, **kwargs)
        finally:
            _MONGO_RECOVERY_DEADLINE.reset(token)

    return wrapper


def _mongo_recovery_deadline() -> float:
    deadline = _MONGO_RECOVERY_DEADLINE.get()
    if deadline is None:
        return asyncio.get_running_loop().time() + FOREGROUND_MONGO_RETRY_SEC
    return deadline


def _propagate_deferred_insert_cancel(fn):
    """Mongo insert 중 받은 취소를 transaction commit 뒤 다시 전달한다."""
    @wraps(fn)
    async def wrapper(*args, **kwargs):
        token = _DEFERRED_INSERT_CANCEL.set(False)
        caller_token = _CALLER_INSERT_CANCEL.set(False)
        try:
            result = await fn(*args, **kwargs)
            if _DEFERRED_INSERT_CANCEL.get():
                raise asyncio.CancelledError
            return result
        finally:
            _CALLER_INSERT_CANCEL.reset(caller_token)
            _DEFERRED_INSERT_CANCEL.reset(token)

    return wrapper


async def _await_with_deferred_cancel(awaitable):
    """현재 awaitable만 drain하고 caller cancellation은 다음 외부 작업 전에 전파한다."""
    if not _DEFER_PENDING_RECOVERY_CANCEL.get():
        return await awaitable
    task = asyncio.create_task(awaitable)
    while True:
        try:
            result = await asyncio.shield(task)
        except asyncio.CancelledError:
            if task.cancelled():
                _DEFERRED_INSERT_CANCEL.set(True)
                raise _AwaitableCancelled from None
            _DEFERRED_INSERT_CANCEL.set(True)
            _CALLER_INSERT_CANCEL.set(True)
            continue
        except BaseException:
            if _CALLER_INSERT_CANCEL.get():
                raise asyncio.CancelledError from None
            raise
        if _CALLER_INSERT_CANCEL.get():
            raise asyncio.CancelledError
        return result


def _is_ambiguous_mongo_error(exc: PyMongoError) -> bool:
    return isinstance(exc, ConnectionFailure) or exc.timeout


async def _retry_after_ambiguous_outcome(deadline: float) -> None:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise PendingRecoveryDeferred("메시지 저장 확인이 지연되고 있습니다.")
    try:
        await _await_with_deferred_cancel(asyncio.sleep(min(0.05, remaining)))
    except _AwaitableCancelled:
        pass


async def _find_with_definitive_outcome(query):
    deadline = _mongo_recovery_deadline()
    while True:
        if asyncio.get_running_loop().time() >= deadline:
            raise PendingRecoveryDeferred("메시지 저장 확인이 지연되고 있습니다.")
        try:
            return await _await_with_deferred_cancel(query())
        except _AwaitableCancelled:
            pass
        except PyMongoError as exc:
            if not _is_ambiguous_mongo_error(exc):
                raise
        await _retry_after_ambiguous_outcome(deadline)


async def _find_inserted_document(message_repo, message_id: str):
    return await _find_with_definitive_outcome(
        lambda: message_repo.find_by_id(message_id),
    )


async def _find_by_client_msg_id(
    message_repo, sender_id: str, client_msg_id: str,
):
    return await _find_with_definitive_outcome(
        lambda: message_repo.find_by_client_msg_id(sender_id, client_msg_id),
    )


async def _insert_with_definitive_outcome(message_repo, document) -> None:
    """Mongo insert의 성공/실패가 확정될 때까지 같은 document로 재시도한다."""
    deadline = _mongo_recovery_deadline()
    while True:
        if asyncio.get_running_loop().time() >= deadline:
            raise PendingRecoveryDeferred(
                "메시지 저장이 지연되어 백그라운드 복구로 전환했습니다.",
            )
        try:
            await _await_with_deferred_cancel(message_repo.insert(document))
            return
        except DuplicateKeyError:
            existing = await _find_inserted_document(
                message_repo, document["_id"],
            )
            if existing is not None and (
                existing.get("chat_room_id") == document["chat_room_id"]
                and existing.get("server_seq") == document["server_seq"]
            ):
                return
            raise
        except _AwaitableCancelled:
            pass
        except PyMongoError as exc:
            if not _is_ambiguous_mongo_error(exc):
                raise
        await _retry_after_ambiguous_outcome(deadline)


async def _force_jump_seq(room_id: str) -> int:
    force_jump = lua_scripts.force_jump
    if force_jump is None:
        raise RuntimeError("chat Lua scripts are not initialized")
    jitter = random.randint(1, SEQ_FORCE_JUMP_JITTER_MAX)
    return int(await force_jump(
        keys=[room_seq_key(room_id)],
        args=[SEQ_FORCE_JUMP_GAP, jitter],
    ))


async def _write_dedupe_ack(redis_dedupe, document) -> None:
    client_msg_id = document.get("client_msg_id")
    sender_id = document.get("sender_id")
    if not client_msg_id or not sender_id:
        return
    await redis_dedupe.set(
        dedupe_key(sender_id, client_msg_id),
        json.dumps({
            "room_id": document["chat_room_id"],
            "message_id": document["_id"],
            "server_seq": document["server_seq"],
            "created_at": document["created_at"].isoformat(),
        }),
        ex=DEDUPE_TTL,
    )


@_with_mongo_recovery_deadline
async def _recover_pending_message(
    redis, redis_dedupe, message_repo, room_id: str, *,
    defer_cancellation: bool = True,
) -> None:
    token = _DEFER_PENDING_RECOVERY_CANCEL.set(defer_cancellation)
    try:
        await _recover_pending_message_inner(
            redis, redis_dedupe, message_repo, room_id,
        )
    finally:
        _DEFER_PENDING_RECOVERY_CANCEL.reset(token)


async def _recover_pending_message_inner(
    redis, redis_dedupe, message_repo, room_id: str,
) -> None:
    key = room_pending_message_key(room_id)
    raw = await redis.get(key)
    if raw is None:
        return
    document = json_util.loads(raw)
    for _attempt in range(_MAX_INSERT_ATTEMPTS):
        try:
            await _insert_with_definitive_outcome(message_repo, document)
            await _write_dedupe_ack(redis_dedupe, document)
            await _finalize_pending_message(redis, room_id)
            return
        except DuplicateKeyError:
            client_msg_id = document.get("client_msg_id")
            sender_id = document.get("sender_id")
            if client_msg_id and sender_id:
                existing = await _find_by_client_msg_id(
                    message_repo, sender_id, client_msg_id,
                )
                if existing is not None:
                    if existing["chat_room_id"] != room_id:
                        try:
                            await _write_dedupe_ack(redis_dedupe, existing)
                        except Exception as exc:
                            logger.warning(
                                "cross-room pending 충돌 ACK 복원 실패: room_id={}, "
                                "existing_room_id={}, err={}",
                                room_id, existing["chat_room_id"], type(exc).__name__,
                            )
                        await _clear_pending_message(redis, room_id)
                        logger.warning(
                            "cross-room client_msg_id 충돌 pending 폐기: room_id={}, "
                            "existing_room_id={}",
                            room_id, existing["chat_room_id"],
                        )
                        return
                    await _write_dedupe_ack(
                        redis_dedupe, existing,
                    )
                    await _finalize_pending_message(redis, room_id)
                    return
            document["server_seq"] = await _force_jump_seq(room_id)
            await _persist_pending_message(redis, document)
        except PyMongoError as exc:
            if _is_ambiguous_mongo_error(exc):
                raise
            client_msg_id = document.get("client_msg_id")
            sender_id = document.get("sender_id")
            if client_msg_id and sender_id:
                await redis_dedupe.delete(
                    dedupe_key(sender_id, client_msg_id),
                )
            await _clear_pending_message(redis, room_id)
            return
    raise UpstreamError("미확정 메시지 복구에 실패했습니다.")


async def _persist_pending_message(redis, document) -> None:
    await _await_with_deferred_cancel(
        redis.set(
            room_pending_message_key(document["chat_room_id"]),
            json_util.dumps(document),
        ),
    )


async def _clear_pending_message(redis, room_id: str) -> None:
    await redis.delete(room_pending_message_key(room_id))


async def _finalize_pending_message(redis, room_id: str) -> None:
    """파생 SQL pointer 복구 표식을 남긴 뒤에만 durable pending을 제거한다."""
    await redis.sadd(DIRTY_CHAT_ROOM_KEY, room_id)
    await _clear_pending_message(redis, room_id)


class MessageService:
    """메시지 송신 핫패스."""

    def __init__(self, uow: UnitOfWork, fanout_service, fcm_service_factory):
        self.uow = uow
        self._fanout = fanout_service
        self._fcm_factory = fcm_service_factory

    @_with_mongo_recovery_deadline
    @_propagate_deferred_insert_cancel
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

        dedupe_k = dedupe_key(sender_user_id, client_msg_id)
        replay = await self._replay_ack_if_available(
            redis_dedupe, dedupe_k, client_msg_id, room_id,
        )
        if replay is not None:
            if await redis_hot.get(room_pending_message_key(room_id)) is None:
                return replay

        # room별 seq 예약과 Mongo insert를 같은 순서로 직렬화한다. 그렇지 않으면 N이
        # in-flight인 동안 N+1이 먼저 저장돼 Mongo max 기반 read가 N까지 선행 처리한다.
        room = await chat_room_repo.find_by_id_for_update(room_id)
        peer_id = None
        if room is not None and cast(ChatRoomType, room.type) == ChatRoomType.DIRECT:
            peer = cast(str | None, (
                room.direct_user_b_id
                if room.direct_user_a_id == sender_user_id
                else room.direct_user_a_id
            ))
            if peer is not None:
                peer_id = str(peer)
                await block_repo.acquire_pair_lock_shared(sender_user_id, peer_id)

        await self._ensure_membership(
            redis_hot, member_repo, room_id=room_id, user_id=sender_user_id,
        )

        count = await lua_scripts.incr_with_ttl(
            keys=[rate_msg_key(sender_user_id)],
            args=[RATE_LIMIT_TTL],
        )
        if count > RATE_LIMIT_THRESHOLD:
            raise ValueError("메시지 전송 속도 제한에 걸렸습니다. 잠시 후 다시 시도해주세요.")

        if room is None:
            raise ValueError("존재하지 않는 방입니다.")

        if peer_id is not None:
            if await self._is_direct_blocked(
                block_repo, sender_user_id=sender_user_id, peer_id=peer_id,
            ):
                raise PermissionError(
                    "차단 관계인 유저에게는 메시지를 보낼 수 없습니다.",
                )

        await _recover_pending_message(
            redis_hot, redis_dedupe, message_repo, room_id,
        )

        # dedupe — NX 선점. placeholder 로 예약 후 Mongo durable 되면 값에 ACK 를 기록한다.
        # 재전송(hit): 값이 ACK 면 원본 ACK 를 replay(전송은 성공했으나 ACK 프레임을 잃은 클라
        # 구제), 아직 placeholder 면 최초 전송이 in-flight → 재시도 유도.
        first_time = await redis_dedupe.set(dedupe_k, _DEDUPE_PENDING, nx=True, ex=DEDUPE_TTL)
        if not first_time:
            replay = await self._replay_ack_if_available(
                redis_dedupe, dedupe_k, client_msg_id, room_id,
                allow_legacy_room=True,
            )
            if replay is not None:
                return replay
            raise ValueError("메시지가 처리 중입니다. 잠시 후 다시 시도해주세요.")

        mongo_durable = False
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
                "client_msg_id": client_msg_id,
                "type": msg_type.value,
                "content": content,
                "created_at": now,
                "edited_at": None,
                "deleted_at": None,
            }

            for attempt in range(_MAX_INSERT_ATTEMPTS):
                try:
                    await _persist_pending_message(redis_hot, doc)
                    await _insert_with_definitive_outcome(message_repo, doc)
                    mongo_durable = True
                    break
                except DuplicateKeyError:
                    existing = await _find_by_client_msg_id(
                        message_repo, sender_user_id, client_msg_id,
                    )
                    if existing is not None:
                        if existing["chat_room_id"] != room_id:
                            raise ValueError(
                                "client_msg_id가 다른 방의 메시지에 이미 사용되었습니다.",
                            )
                        await _write_dedupe_ack(
                            redis_dedupe, existing,
                        )
                        await _finalize_pending_message(redis_hot, room_id)
                        return MessageSentAckData(
                            client_msg_id=client_msg_id,
                            message_id=existing["_id"],
                            server_seq=int(existing["server_seq"]),
                            created_at=existing["created_at"],
                        )
                    server_seq = await _force_jump_seq(room_id)
                    doc["server_seq"] = server_seq
            else:
                logger.error(
                    "메시지 저장 {}회 연속 DuplicateKey: room_id={}, user_id={}",
                    _MAX_INSERT_ATTEMPTS, room_id, sender_user_id,
                )
                raise UpstreamError("메시지 저장에 실패했습니다. 잠시 후 다시 시도해주세요.")

            await _write_dedupe_ack(redis_dedupe, doc)
            await _finalize_pending_message(redis_hot, room_id)

        except PendingRecoveryDeferred:
            raise
        except Exception:
            if not mongo_durable:
                await _clear_pending_message(redis_hot, room_id)
                await redis_dedupe.delete(dedupe_k)
            raise

        # 같은 커넥션의 SAVEPOINT와 if_greater로 pool deadlock 및 seq regress를 피한다.
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

        # durable 저장 뒤 unread/fanout 실패를 전파하면 ACK와 last_message만 유실된다.
        if msg_type != MessageType.SYSTEM:
            try:
                await self._bump_unread(
                    redis_hot,
                    room_id=room_id,
                    sender_user_id=sender_user_id,
                    server_seq=server_seq,
                )
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

        # FCM은 durable 저장 후 fire-and-forget으로 ACK를 지연시키지 않는다.
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
        """RDB 멤버십을 검증하고 방 멤버 캐시를 준비."""
        if not await member_repo.is_active_member_for_share(room_id, user_id):
            raise PermissionError("이 방의 멤버가 아닙니다.")

        key = room_members_key(room_id)
        is_member = await redis_hot.sismember(key, user_id)
        if is_member:
            # unread/FCM이 읽기 전 만료되지 않도록 sliding TTL을 갱신한다.
            await redis_hot.expire(key, ROOM_MEMBERS_TTL)
            return

        # DB 읽기 직전 generation을 캡처해 leave/kick 뒤 stale cache 부활을 막는다.
        gen_key = room_members_gen_key(room_id)
        gen0 = await redis_hot.get(gen_key) or "0"

        members = await member_repo.find_active_member_ids(room_id)
        if not members:
            raise ValueError("존재하지 않는 방이거나 멤버가 없습니다.")

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
    async def _replay_ack_if_available(
        redis_dedupe, dedupe_k: str, client_msg_id: str, room_id: str, *,
        allow_legacy_room: bool = False,
    ) -> MessageSentAckData | None:
        """같은 방의 dedupe ACK를 복원."""
        raw = await redis_dedupe.get(dedupe_k)
        if not raw or raw == _DEDUPE_PENDING:
            return None
        try:
            data = json.loads(raw)
            stored_room_id = data.get("room_id")
            if stored_room_id != room_id and not (
                allow_legacy_room and stored_room_id is None
            ):
                return None
            return MessageSentAckData(
                client_msg_id=client_msg_id,
                message_id=data["message_id"],
                server_seq=int(data["server_seq"]),
                created_at=datetime.fromisoformat(data["created_at"]),
            )
        except (ValueError, TypeError, KeyError):
            return None

    @_with_mongo_recovery_deadline
    @_propagate_deferred_insert_cancel
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
        redis_dedupe = await get_redis_dedupe_client()

        # 일반 메시지와 같은 room mutex를 사용해 모든 seq의 Mongo commit 순서를 보장한다.
        room = await chat_room_repo.find_by_id_for_update(room_id)
        if room is None:
            raise ValueError("존재하지 않는 방입니다.")

        await _recover_pending_message(
            redis_hot, redis_dedupe, message_repo, room_id,
        )

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

        mongo_durable = False
        try:
            for attempt in range(_MAX_INSERT_ATTEMPTS):
                try:
                    await _persist_pending_message(redis_hot, doc)
                    await _insert_with_definitive_outcome(message_repo, doc)
                    mongo_durable = True
                    break
                except DuplicateKeyError:
                    server_seq = await _force_jump_seq(room_id)
                    doc["server_seq"] = server_seq
            else:
                logger.error(
                    "시스템 메시지 {}회 연속 실패: room_id={}, action={}",
                    _MAX_INSERT_ATTEMPTS, room_id, action,
                )
                raise UpstreamError("시스템 메시지 저장에 실패했습니다.")

            await _finalize_pending_message(redis_hot, room_id)
        except PendingRecoveryDeferred:
            raise
        except Exception:
            if not mongo_durable:
                await _clear_pending_message(redis_hot, room_id)
            raise

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
        block_repo: UserBlockRepository,
        *,
        sender_user_id: str,
        peer_id: str,
    ) -> bool:
        """1:1 방의 양방향 차단 상태를 RDB에서 확인한다."""
        return bool(await block_repo.find_blocks_between(sender_user_id, peer_id))

    @staticmethod
    async def _bump_unread(
        redis_hot, *, room_id: str, sender_user_id: str, server_seq: int,
    ) -> None:
        """발신자 제외 멤버의 unread와 message watermark를 한 Lua로 갱신."""
        key = room_members_key(room_id)
        members = await redis_hot.smembers(key)
        recipients = [uid for uid in members if uid != sender_user_id]
        if not recipients:
            return

        keys: list[str] = []
        for uid in recipients:
            keys.extend([unread_key(uid), unread_watermark_key(uid)])
        try:
            await lua_scripts.increment_unread(
                keys=keys, args=[room_id, server_seq],
            )
        except Exception as e:
            logger.warning(
                "unread pipeline 실패 (무시하고 진행): room_id={}, err={}",
                room_id, type(e).__name__,
            )

    def _spawn_push_task(
        self, *, room_id: str, sender_user_id: str, content: str,
    ) -> None:
        """푸시 task를 앱 lifecycle supervisor에 등록한다."""
        background_tasks.spawn(
            self._push_chat_to_recipients(
                room_id=room_id,
                sender_user_id=sender_user_id,
                content=content,
            ),
            name=f"chat-push-{room_id}",
        )

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
