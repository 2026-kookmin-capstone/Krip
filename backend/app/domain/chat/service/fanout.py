"""채팅 이벤트 fan-out.

`settings.FANOUT_MODE`:
- `in_process`   : 단일 프로세스 메모리 dict 직배송
- `node_channel` : 다중 노드 Redis Pub/Sub (`node:{node_id}` 채널)

호출측은 모드 무관 — `fan_out_to_*` / `(un)subscribe_user_to_room` 만 사용.

WS 객체 duck typing 전제 — 핸들러가 `session_id` / `user_id` / `subscribed_rooms` 를 심는다.

`node_channel` 모드에서 publisher 는 자기 자신에게도 publish 해 `_local_*` 로 들어가는
통일 경로를 유지 (모드별 분기 최소화). 동일 채널 내 ordering 은 Redis 가 보장하므로
"subscribe → fan_out" 순서가 모든 노드에서 보존된다.

`NODE_ID`: uvicorn `--workers N` 운영 시 충돌하면 한 채널을 여러 워커가 동시 구독해
중복 수신이 발생 — 명시 지정 권장.
"""
import asyncio
import json
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.websockets import WebSocket, WebSocketDisconnect

from app.config.setting import settings
from app.core.background_tasks import background_tasks
from app.core.chat.redis_key import node_channel_key, ws_route_key
from app.core.context import request_id_var, traceparent_var
from app.core.instrumentation import (
    chat_fanout_dispatch,
    chat_fanout_publish_inc,
)
from app.core.logger import get_logger
from app.core.redis import get_redis_client
from app.database.session import mongodb
from app.domain.auth.repository.user import UserRepository
from app.domain.chat.repository.chat_member import ChatRoomMemberRepository
from app.domain.chat.repository.chat_message import ChatMessageRepository
from app.domain.chat.worker.node_registry import list_active_nodes


logger = get_logger("chat.fanout")


_SUPPORTED_MODES = ("in_process", "node_channel")

# session_revoked 전달 후 서버가 소켓을 닫을 close code (ws.py 의 CLOSE_AUTH_EXPIRED 와 동일 —
# 클라는 "재인증 필요" 로 처리).
_CLOSE_SESSION_REVOKED = 4001

# 응답 없는(백프레셔로 stuck) 소켓을 서버가 강제 종료할 때의 close code. 클라는 재접속으로 회복.
_CLOSE_UNRESPONSIVE = 1011

# 개별 WS send 상한 — 정체된 클라이언트(TCP 백프레셔)가 노드 전체 fan-out 을 멈추는
# head-of-line 블로킹 차단. 초과 소켓은 dead 로 간주해 정리한다.
_SEND_TIMEOUT_SECONDS = 5

# 같은 방의 local acceptance와 bounded socket write를 직렬화하는 fixed-size stripe.
_ROOM_DELIVERY_LOCK_STRIPES = 256

# subscription reconcile 실패(fail-closed unsubscribe) 후 재시도 지연. 소진되면
# 다음 membership 이벤트 또는 WS 재연결이 최종 복구 경로다.
_RECONCILE_RETRY_DELAYS = (1.0, 5.0, 15.0)


def _normalize_instant(value: object) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.replace(microsecond=(value.microsecond // 1000) * 1000)


def _same_instant(left: object, right: object) -> bool:
    left_at = _normalize_instant(left)
    right_at = _normalize_instant(right)
    return left_at is not None and left_at == right_at


def _iso_or_none(value: object) -> str | None:
    instant = _normalize_instant(value)
    return instant.isoformat() if instant is not None else None


def _message_id_for_delivery(payload: dict) -> str | None:
    event_type = payload.get("type")
    if event_type not in {"message.new", "message.updated", "message.deleted"}:
        return None
    message = payload.get("message") if event_type == "message.new" else payload
    if not isinstance(message, dict):
        return None
    message_id = message.get("message_id")
    return message_id if isinstance(message_id, str) else None


class FanoutAuthorizationService:
    """로컬 전달 직전에 authoritative SQL 수신 권한을 배치 확인한다."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    @asynccontextmanager
    async def lock_room_delivery(
        self, room_id: str, user_ids: set[str], *, message_id: str | None = None,
    ) -> AsyncIterator[set[str]]:
        """메시지 mutation 및 수신 권한 lock을 socket 전송 종료까지 유지한다."""
        async with self._session_factory() as session:
            if message_id is not None:
                await session.execute(
                    text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_name, 0))"),
                    {"lock_name": f"chat-message-mutation:{message_id}"},
                )
            yield await ChatRoomMemberRepository(
                session,
            ).lock_active_receiving_user_ids(room_id, user_ids)

    @asynccontextmanager
    async def lock_user_delivery(self, user_id: str) -> AsyncIterator[bool]:
        """계정 status SHARE lock을 실제 socket 전송 종료까지 유지한다."""
        async with self._session_factory() as session:
            yield await UserRepository(session).lock_if_active(user_id)

    @asynccontextmanager
    async def lock_room_subscription(
        self, room_id: str, user_id: str,
    ) -> AsyncIterator[bool]:
        """inactive membership도 잠가 delayed envelope과 reinvite를 직렬화한다."""
        async with self._session_factory() as session:
            yield await ChatRoomMemberRepository(session).lock_receiving_state(
                room_id, user_id,
            )

    async def prepare_current_message_event(
        self, payload: dict, *, room_id: str | None = None,
    ) -> bool:
        """Mongo durable revision과 일치하는 message event만 허용한다."""
        event_type = payload.get("type")
        if event_type not in {"message.new", "message.updated", "message.deleted"}:
            return True

        message = payload.get("message") if event_type == "message.new" else payload
        if not isinstance(message, dict):
            return False
        message_id = message.get("message_id")
        if not isinstance(message_id, str):
            return False

        database = mongodb.database
        if database is None:
            return False
        doc = await ChatMessageRepository(database).find_by_id(message_id)
        if doc is None:
            return False
        if room_id is not None and str(doc.get("chat_room_id")) != room_id:
            return False

        if event_type == "message.new":
            if not _same_instant(doc.get("created_at"), message.get("created_at")):
                return False
            canonical_message = {
                "message_id": message_id,
                "chat_room_id": str(doc.get("chat_room_id")),
                "server_seq": doc.get("server_seq", message.get("server_seq")),
                "sender_id": doc.get("sender_id"),
                "type": getattr(doc.get("type"), "value", doc.get("type")),
                "content": None if doc.get("deleted_at") is not None else doc.get("content"),
                "created_at": _iso_or_none(doc.get("created_at")),
                "edited_at": _iso_or_none(doc.get("edited_at")),
                "deleted_at": _iso_or_none(doc.get("deleted_at")),
            }
            sender_session_id = payload.get("sender_session_id")
            payload.clear()
            payload.update(
                type="message.new",
                sender_session_id=(sender_session_id if isinstance(sender_session_id, str) else ""),
                message=canonical_message,
            )
            return True
        if event_type == "message.updated":
            is_current = (
                doc.get("deleted_at") is None
                and doc.get("content") == payload.get("content")
                and _same_instant(doc.get("edited_at"), payload.get("edited_at"))
            )
            if not is_current:
                return False
            sender_session_id = payload.get("sender_session_id")
            payload.clear()
            payload.update(
                type="message.updated",
                sender_session_id=(sender_session_id if isinstance(sender_session_id, str) else ""),
                message_id=message_id,
                content=doc.get("content"),
                edited_at=_iso_or_none(doc.get("edited_at")),
            )
            return True

        if not _same_instant(doc.get("deleted_at"), payload.get("deleted_at")):
            return False
        sender_session_id = payload.get("sender_session_id")
        payload.clear()
        payload.update(
            type="message.deleted",
            sender_session_id=(sender_session_id if isinstance(sender_session_id, str) else ""),
            message_id=message_id,
            deleted_at=_iso_or_none(doc.get("deleted_at")),
        )
        return True


class FanoutService:
    """fan-out 인터페이스 — 모드별 분기는 본 클래스 내부에 격리.

    Singleton 으로 등록. `node_channel` 모드에서도 로컬 dict 는 유지 — 디스패처가
    envelope 을 받아 `_local_*` 로 재진입할 때 사용.
    """

    def __init__(self, authorization_service: FanoutAuthorizationService):
        if settings.FANOUT_MODE not in _SUPPORTED_MODES:
            raise NotImplementedError(
                f"FANOUT_MODE={settings.FANOUT_MODE!r} 미지원. "
                f"지원 모드: {_SUPPORTED_MODES}",
            )
        self._mode = settings.FANOUT_MODE
        self._authorization = authorization_service
        self._room_subs: dict[str, set[WebSocket]] = defaultdict(set)
        self._user_subs: dict[str, set[WebSocket]] = defaultdict(set)
        self._local_ws_by_session: dict[str, WebSocket] = {}
        self._latest_room_message_seq: dict[str, int] = {}
        self._room_delivery_locks = tuple(
            asyncio.Lock() for _ in range(_ROOM_DELIVERY_LOCK_STRIPES)
        )
        self._pending_reconcile_retries: set[tuple[str, str]] = set()

    # WS 가 이 노드에 붙어있는 것이라 cross-node 전파 불필요.

    def register_session(self, ws: WebSocket) -> None:
        """WS 연결 시 세션 등록 (방 구독은 별도).

        호출 전 핸들러가 `session_id` / `user_id` / `subscribed_rooms` 를 심어야 한다.
        """
        self._local_ws_by_session[ws.session_id] = ws
        self._user_subs[ws.user_id].add(ws)

    def register_ws_to_room(self, ws: WebSocket, room_id: str) -> None:
        """방 구독. 역매핑 `ws.subscribed_rooms` 도 갱신해 종료 시 O(1) 해제."""
        self._room_subs[room_id].add(ws)
        ws.subscribed_rooms.add(room_id)

    def unregister_ws(self, ws: WebSocket) -> None:
        """WS 종료 시 모든 dict 에서 제거. 반드시 close / Redis 정리보다 먼저 호출 —
        dispatcher 가 dead 소켓에 push 하지 않도록.
        """
        sid: str | None = getattr(ws, "session_id", None)
        uid: str | None = getattr(ws, "user_id", None)
        rooms: set[str] = getattr(ws, "subscribed_rooms", set())

        if sid is not None:
            self._local_ws_by_session.pop(sid, None)

        if uid is not None and uid in self._user_subs:
            self._user_subs[uid].discard(ws)
            if not self._user_subs[uid]:
                del self._user_subs[uid]

        for room_id in list(rooms):
            if room_id in self._room_subs:
                self._room_subs[room_id].discard(ws)
                if not self._room_subs[room_id]:
                    del self._room_subs[room_id]
                    self._cleanup_room_state_if_empty(room_id)

    @staticmethod
    def _spawn_close(ws: WebSocket, code: int = _CLOSE_UNRESPONSIVE) -> None:
        """소켓 close 를 백그라운드 task 로 실행. 이미 닫힌 소켓이면 무해한 no-op.

        수신 loop 가 같은 소켓에서 receive 중이어도, close 프레임이 disconnect 로 이어져
        loop 가 정상 종료 + 자체 cleanup(멱등) 을 수행한다. session_revoked 종료와 동일 패턴.
        """
        async def _close() -> None:
            try:
                await ws.close(code=code)
            except Exception:
                pass

        background_tasks.spawn(
            _close(),
            name=f"chat-ws-close-{getattr(ws, 'session_id', 'unknown')}",
        )

    async def subscribe_user_to_room(
        self, user_id: str, room_id: str, *, authorization_locked: bool = False,
    ) -> None:
        """유저의 모든 세션 (전 노드) 을 방 구독에 추가. invite / 방 생성 시 호출.

        호출 전에 RDB `chat_room_member` 와 Redis `room_members` 캐시가 먼저 갱신되어야 한다.
        오프라인 유저는 no-op. Idempotent.

        `authorization_locked=True`는 caller가 ACTIVE account/membership generation
        locks를 유지하는 동안만 사용한다. in-process에서 별도 SQL transaction을 열지 않아
        connection-pool circular wait를 피한다.
        """
        if self._mode == "in_process":
            if authorization_locked:
                self._local_subscribe_user_to_room(user_id, room_id)
            else:
                await self._reconcile_room_subscription(user_id, room_id)
            return
        await self._publish_broadcast(
            {"op": "subscribe", "user_id": user_id, "room_id": room_id},
        )

    async def unsubscribe_user_from_room(self, user_id: str, room_id: str) -> None:
        """유저의 모든 세션 (전 노드) 을 방 구독에서 제거. leave / kick 시 호출.

        반드시 시스템 메시지 fan-out 이전에 호출:
        1) leak 차단 — send_system_message 가 실패해도 이미 구독 해제됨
        2) UX — 퇴장 당사자가 자기 퇴장 시스템 메시지를 받지 않음
        """
        await self._reconcile_room_subscription(user_id, room_id)
        if self._mode == "in_process":
            return
        await self._publish_broadcast(
            {"op": "unsubscribe", "user_id": user_id, "room_id": room_id},
        )

    async def fan_out_to_room(self, room_id: str, payload: dict) -> None:
        """방의 활성 WS 전체에 브로드캐스트. `payload.sender_session_id` 가 있으면 발신자 skip."""
        if self._mode == "in_process":
            await self._local_deliver_to_room(room_id, payload)
            return
        await self._publish_broadcast(
            {"op": "room", "room_id": room_id, "payload": payload},
        )

    async def fan_out_to_user(self, user_id: str, payload: dict) -> None:
        """유저의 모든 세션에 브로드캐스트 (`room_joined` / `unread_synced` 등 user-scoped)."""
        if self._mode == "in_process":
            await self._local_deliver_to_user(user_id, payload)
            return
        await self._publish_broadcast(
            {"op": "user", "user_id": user_id, "payload": payload},
        )

    async def fan_out_member_removed(self, user_id: str, room_id: str) -> None:
        """membership-revocation control delivery. 커밋 후 room lock 없이 호출한다 —
        전달 직전 membership 재확인(checked)으로 stale 이벤트를 걸러낸다.
        """
        if self._mode == "in_process":
            await self._local_deliver_member_removed(user_id, room_id)
            return
        await self._publish_broadcast(
            {"op": "member_removed", "user_id": user_id, "room_id": room_id},
        )

    async def fan_out_member_joined(self, user_id: str, room_id: str) -> None:
        """membership-grant control delivery. 커밋 후 room lock 없이 호출한다 —
        전달 직전 membership 재확인(checked)으로 stale 이벤트를 걸러낸다.
        """
        if self._mode == "in_process":
            await self._local_deliver_member_joined(user_id, room_id)
            return
        await self._publish_broadcast(
            {"op": "member_joined", "user_id": user_id, "room_id": room_id},
        )

    async def fan_out_to_session(self, session_id: str, payload: dict) -> None:
        """특정 세션 직송. `node_channel` 모드는 `ws_route:{sid}` 로 타깃 노드 라우팅.

        라우트가 없으면 세션 사라진 것 — silent drop.
        """
        if self._mode == "in_process":
            await self._local_deliver_to_session(session_id, payload)
            return
        await self._publish_to_session_node(session_id, payload)

    async def dispatch_envelope(self, envelope: dict) -> None:
        """`FanoutDispatcher` 가 Pub/Sub 메시지를 받아 호출.

        알 수 없는 op 는 warning 후 drop (구/신버전 노드 혼재 fail-open).
        publisher 가 박은 request_id / traceparent 를 contextvar 로 복원 — cross-node trace 보존.
        """
        op = envelope.get("op", "unknown")

        rid_token = request_id_var.set(envelope.get("request_id", ""))
        tp_token = traceparent_var.set(envelope.get("traceparent", ""))

        try:
            async with chat_fanout_dispatch(op):
                try:
                    if op == "room":
                        await self._local_deliver_to_room(
                            envelope["room_id"], envelope["payload"],
                        )
                    elif op == "user":
                        await self._local_deliver_to_user(
                            envelope["user_id"], envelope["payload"],
                        )
                    elif op == "member_removed":
                        await self._local_deliver_member_removed(
                            envelope["user_id"], envelope["room_id"],
                        )
                    elif op == "member_joined":
                        await self._local_deliver_member_joined(
                            envelope["user_id"], envelope["room_id"],
                        )
                    elif op == "session":
                        await self._local_deliver_to_session(
                            envelope["session_id"], envelope["payload"],
                        )
                    elif op == "subscribe":
                        await self._reconcile_room_subscription(
                            envelope["user_id"], envelope["room_id"],
                        )
                    elif op == "unsubscribe":
                        await self._reconcile_room_subscription(
                            envelope["user_id"], envelope["room_id"],
                        )
                    else:
                        logger.warning("알 수 없는 envelope op (drop): {}", op)
                except KeyError as e:
                    logger.warning(
                        "envelope 필드 누락 (drop): op={}, missing={}", op, e,
                    )
        finally:
            request_id_var.reset(rid_token)
            traceparent_var.reset(tp_token)

    async def _reconcile_room_subscription(
        self, user_id: str, room_id: str, *, attempt: int = 0,
    ) -> None:
        """현재 DB membership만 반영해 delayed subscribe/unsubscribe를 무해화한다.

        조회 실패 시 fail-closed unsubscribe 후 bounded retry를 예약한다 — 일시적 DB
        장애가 온라인 멤버의 live 수신을 재접속 전까지 끊어놓지 않도록.
        """
        try:
            async with self._authorization.lock_room_subscription(
                room_id, user_id,
            ) as should_subscribe:
                if should_subscribe:
                    self._local_subscribe_user_to_room(user_id, room_id)
                else:
                    self._local_unsubscribe_user_from_room(user_id, room_id)
        except Exception as e:
            logger.warning(
                "room subscription 상태 조회 실패 (fail-closed unsubscribe): "
                "room_id={}, user_id={}, attempt={}, err={}",
                room_id, user_id, attempt, type(e).__name__,
            )
            # fail-closed는 최초 이벤트에서만 적용한다. retry 실패는 새 authorization
            # 이벤트가 아니므로, 그 사이 정당하게(authorization_locked/성공 reconcile)
            # 재구독된 상태를 철회하지 않는다.
            if attempt == 0:
                self._local_unsubscribe_user_from_room(user_id, room_id)
            self._schedule_reconcile_retry(user_id, room_id, failed_attempt=attempt)

    def _schedule_reconcile_retry(
        self, user_id: str, room_id: str, *, failed_attempt: int,
    ) -> None:
        """(user, room) 당 1개의 pending retry만 허용해 재시도 폭주를 막는다."""
        if failed_attempt >= len(_RECONCILE_RETRY_DELAYS):
            logger.error(
                "room subscription reconcile 재시도 소진 — WS 재연결 전까지 "
                "live 수신 누락 가능: room_id={}, user_id={}",
                room_id, user_id,
            )
            return
        key = (user_id, room_id)
        if key in self._pending_reconcile_retries:
            return
        self._pending_reconcile_retries.add(key)

        async def _retry() -> None:
            try:
                await asyncio.sleep(_RECONCILE_RETRY_DELAYS[failed_attempt])
            finally:
                self._pending_reconcile_retries.discard(key)
            if not self._user_subs.get(user_id):
                return  # 이 노드에 세션이 없으면 복구할 구독도 없다.
            await self._reconcile_room_subscription(
                user_id, room_id, attempt=failed_attempt + 1,
            )

        task = background_tasks.spawn(
            _retry(),
            name=f"chat-subscription-reconcile-{room_id}-{user_id}",
        )
        if task is None:  # shutdown 중 등록 거부 — pending 표시 원복
            self._pending_reconcile_retries.discard(key)

    def _local_subscribe_user_to_room(self, user_id: str, room_id: str) -> None:
        """이 노드의 user_id 세션들을 `_room_subs[room_id]` 에 추가. dead WS 는 가드로 skip."""
        for ws in list(self._user_subs.get(user_id, ())):
            sid = getattr(ws, "session_id", None)
            if sid is None or sid not in self._local_ws_by_session:
                continue
            self.register_ws_to_room(ws, room_id)

    def _local_unsubscribe_user_from_room(self, user_id: str, room_id: str) -> None:
        """이 노드의 user_id 세션들을 `_room_subs[room_id]` 에서 제거."""
        affected = list(self._user_subs.get(user_id, ()))
        if not affected:
            return

        room_set = self._room_subs.get(room_id)
        for ws in affected:
            rooms = getattr(ws, "subscribed_rooms", None)
            if rooms is not None:
                rooms.discard(room_id)
            if room_set is not None:
                room_set.discard(ws)

        if room_set is not None and not room_set:
            del self._room_subs[room_id]
            self._cleanup_room_state_if_empty(room_id)

    def _cleanup_room_state_if_empty(self, room_id: str) -> None:
        if room_id in self._room_subs:
            return
        self._latest_room_message_seq.pop(room_id, None)

    async def _local_deliver_to_room(self, room_id: str, payload: dict) -> None:
        lock = self._room_delivery_locks[hash(room_id) % _ROOM_DELIVERY_LOCK_STRIPES]
        async with lock:
            await self._local_deliver_to_room_locked(room_id, payload)

    async def _local_deliver_to_room_locked(self, room_id: str, payload: dict) -> None:
        sender_sid = payload.get("sender_session_id")
        candidates = [
            ws for ws in self._room_subs.get(room_id, ())
            if ws.session_id != sender_sid
        ]
        if not candidates:
            return
        async with self._authorization.lock_room_delivery(
            room_id,
            {ws.user_id for ws in candidates},
            message_id=_message_id_for_delivery(payload),
        ) as active_user_ids:
            if not await self._accept_room_payload(room_id, payload):
                return
            recipients = [ws for ws in candidates if ws.user_id in active_user_ids]
            await self._broadcast(recipients, payload)

    async def _accept_room_payload(self, room_id: str, payload: dict) -> bool:
        """durable current event만 허용하고 new-message high watermark를 관찰한다."""
        try:
            if not await self._authorization.prepare_current_message_event(
                payload, room_id=room_id,
            ):
                return False
        except Exception as e:
            logger.warning(
                "message fanout revision 조회 실패 (fail-closed): room_id={}, err={}",
                room_id, type(e).__name__,
            )
            return False

        event_type = payload.get("type")
        if event_type == "message.new":
            message = payload.get("message")
            if isinstance(message, dict):
                server_seq = message.get("server_seq")
                if isinstance(server_seq, int):
                    latest_seq = self._latest_room_message_seq.get(room_id, 0)
                    if server_seq > latest_seq:
                        self._latest_room_message_seq[room_id] = server_seq
        return True

    async def _local_deliver_to_user(self, user_id: str, payload: dict) -> None:
        recipients = list(self._user_subs.get(user_id, ()))
        if not recipients:
            return
        async with self._authorization.lock_user_delivery(user_id) as is_active:
            if not is_active:
                for ws in recipients:
                    self.unregister_ws(ws)
                    try:
                        await ws.close(code=_CLOSE_SESSION_REVOKED)
                    except Exception:
                        pass
                return
            await self._broadcast(recipients, payload)

    async def _local_deliver_member_removed(self, user_id: str, room_id: str) -> None:
        async with self._authorization.lock_room_subscription(
            room_id, user_id,
        ) as is_active_member:
            if is_active_member:
                return
            await self._local_deliver_member_removed_unchecked(user_id, room_id)

    async def _local_deliver_member_removed_unchecked(
        self, user_id: str, room_id: str,
    ) -> None:
        await self._broadcast(
            list(self._user_subs.get(user_id, ())),
            {"type": "room_left", "room_id": room_id},
        )

    async def _local_deliver_member_joined(self, user_id: str, room_id: str) -> None:
        async with self._authorization.lock_room_subscription(
            room_id, user_id,
        ) as is_active_member:
            if not is_active_member:
                return
            await self._local_deliver_member_joined_unchecked(user_id, room_id)

    async def _local_deliver_member_joined_unchecked(
        self, user_id: str, room_id: str,
    ) -> None:
        await self._broadcast(
            list(self._user_subs.get(user_id, ())),
            {"type": "room_joined", "room_id": room_id},
        )

    async def _local_deliver_to_session(self, session_id: str, payload: dict) -> None:
        ws = self._local_ws_by_session.get(session_id)
        if ws is None:
            return
        await self._broadcast([ws], payload)

        # session_revoked 는 이벤트만 보내면 클라가 무시할 때 소켓이 살아남아 계속 수신한다
        # (탈퇴/강제 로그아웃 누수). 서버가 직접 구독 해제 + 소켓 종료해 클라 협조에 의존하지 않는다.
        if payload.get("type") == "session_revoked":
            self.unregister_ws(ws)
            try:
                await ws.close(code=_CLOSE_SESSION_REVOKED)
            except Exception:
                pass

    @staticmethod
    async def _publish_broadcast(envelope: dict) -> None:
        """활성 노드 전체 (자기 자신 포함) 에 publish.

        자기 자신에게도 publish → 디스패처가 받아 `_local_*` 로 들어가는 통일 경로 유지.
        활성 노드 0 명이면 publish skip. envelope 에 request_id/traceparent 박아 trace 보존.
        """
        nodes = await list_active_nodes()
        if not nodes:
            return

        envelope.setdefault("request_id", request_id_var.get())
        envelope.setdefault("traceparent", traceparent_var.get())

        chat_fanout_publish_inc(envelope.get("op", "unknown"))

        redis = await get_redis_client()
        envelope_json = json.dumps(envelope)
        pipe = redis.pipeline(transaction=False)
        for node_id in nodes:
            pipe.publish(node_channel_key(node_id), envelope_json)
        await pipe.execute()

    @staticmethod
    async def _publish_to_session_node(session_id: str, payload: dict) -> None:
        """특정 세션이 붙은 노드에만 publish. 라우트가 없으면 세션 만료 — silent drop."""
        redis = await get_redis_client()
        target_node = await redis.get(ws_route_key(session_id))
        if target_node is None:
            return

        envelope = {
            "op": "session",
            "session_id": session_id,
            "payload": payload,
            "request_id": request_id_var.get(),
            "traceparent": traceparent_var.get(),
        }
        chat_fanout_publish_inc("session")
        await redis.publish(node_channel_key(target_node), json.dumps(envelope))

    async def _broadcast(self, recipients: list[WebSocket], payload: dict) -> None:
        """여러 WS 에 동시 push — `gather(return_exceptions=True)` 로 한 WS 실패 격리.

        각 send 에 `_SEND_TIMEOUT_SECONDS` 상한. dead 세션(RuntimeError / WebSocketDisconnect
        / 타임아웃)은 즉시 unregister(좀비 워닝 폭발 차단), 그 외 예외는 일시적일 수 있어 로그만.
        """
        if not recipients:
            return
        results = await asyncio.gather(
            *(
                asyncio.wait_for(ws.send_json(payload), timeout=_SEND_TIMEOUT_SECONDS)
                for ws in recipients
            ),
            return_exceptions=True,
        )
        for ws, result in zip(recipients, results):
            if not isinstance(result, BaseException):
                continue
            logger.warning(
                "fan-out send 실패: session_id={}, err={!r}",
                getattr(ws, "session_id", "?"),
                result,
            )
            # 타임아웃(백프레셔로 stuck)도 dead 로 간주 — 느린 소켓이 노드 전체 전달을 막지 않게.
            if isinstance(result, (
                RuntimeError,
                WebSocketDisconnect,
                asyncio.TimeoutError,
                asyncio.CancelledError,
            )):
                self.unregister_ws(ws)
                # unregister 만 하면 "수신만 끊긴 좀비"(소켓은 살아 세션 TTL 계속 갱신)가 된다.
                # 소켓을 닫아 재접속을 유도 — 닫기는 백그라운드로 fan-out 을 막지 않게.
                self._spawn_close(ws)
