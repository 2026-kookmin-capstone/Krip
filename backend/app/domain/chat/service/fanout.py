"""채팅 이벤트 fan-out.

Phase 1~3 는 단일 FastAPI 프로세스의 메모리 dict 로 동작하고, Phase 4 에서 다중 노드
`node:{node_id}` Pub/Sub 모델로 전환한다. 동일한 인터페이스
(`fan_out_to_room` / `fan_out_to_user` / `fan_out_to_session`) 뒤에 두 모드를 숨겨
Phase 4 전환 시 서비스/라우터 코드는 건드리지 않도록 한다.

**WS 객체 전제 (duck typing)**:
    - `ws.session_id: str`
    - `ws.user_id: str`
    - `ws.subscribed_rooms: set[str]`
연결 핸들러(`chat_ws_router`) 가 `WebSocket` 인스턴스에 이 세 속성을 심어두고
`register_session` + `register_ws_to_room` 을 호출한다.
"""
from typing import Any
from fastapi import WebSocket
from collections import defaultdict
import asyncio

from app.config.setting import settings
from app.core.logger import get_logger


logger = get_logger("chat.fanout")


class FanoutService:
    """in-process fan-out (Phase 1~3 구현).

    Singleton 으로 Container 에 등록되어 프로세스 전체가 동일한 dict 를 공유한다.
    `FANOUT_MODE=node_channel` 모드는 Phase 4 진입 시 이 클래스에 분기 추가 예정 —
    지금은 잘못된 설정 조기 발견을 위해 `__init__` 에서 가드.
    """

    def __init__(self):
        if settings.FANOUT_MODE != "in_process":
            raise NotImplementedError(
                f"FANOUT_MODE={settings.FANOUT_MODE!r} 는 Phase 4 에서 구현 예정. "
                "Phase 1~3 는 'in_process' 만 지원."
            )
        self._room_subs: dict[str, set[WebSocket]] = defaultdict(set)
        self._user_subs: dict[str, set[WebSocket]] = defaultdict(set)
        self._local_ws_by_session: dict[str, WebSocket] = {}


    # ──────────────────── 등록 / 해제 ────────────────────

    def register_session(self, ws: WebSocket) -> None:
        """WS 연결 시 세션 단위 등록 (방 구독은 별도).

        호출 전 핸들러가 반드시 `ws.session_id` / `ws.user_id` / `ws.subscribed_rooms`
        속성을 심어둬야 한다.
        """
        self._local_ws_by_session[ws.session_id] = ws
        self._user_subs[ws.user_id].add(ws)


    def register_ws_to_room(self, ws: WebSocket, room_id: str) -> None:
        """방 구독. 역매핑(`ws.subscribed_rooms`) 을 함께 갱신해 종료 시 O(1) 해제."""
        self._room_subs[room_id].add(ws)
        ws.subscribed_rooms.add(room_id)


    def unregister_ws(self, ws: WebSocket) -> None:
        """WS 종료 시 모든 dict 에서 제거.

        **반드시 `ws.close()` 또는 Redis 정리보다 먼저** 호출되어야 dispatcher 가
        이미 close 된 소켓에 push 하지 않는다. 빈 set 은 함께 pop 해
        메모리 누수 방지.
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


    # ──────────────────── 동적 방 구독 (invite / leave / kick) ────────────────────

    def subscribe_user_to_room(self, user_id: str, room_id: str) -> None:
        """유저의 모든 로컬 세션을 방 구독에 추가. invite / 방 생성 시 호출.

        WS 가 처음 연결될 때 (`ws.py` 의 `list_user_room_ids` 경로) 구독되는 정적
        등록과 짝을 이루는 동적 등록 — 그 이후 새로 가입한 방에 대해 호출. 호출 전에
        RDB `chat_room_member` 와 Redis `room_members` 캐시가 먼저 갱신되어야 한다
        (시스템 메시지 fan-out 이전에 구독되어야 자기 초대된 메시지 수신).

        오프라인 유저는 `_user_subs.get(user_id, ())` 가 빈 set 이라 no-op — 다음 WS
        연결 시 정적 등록 경로로 자연스럽게 채워진다.

        Idempotent — `set.add` 로 중복 호출 안전. unregister 진행 중인 dead WS 는
        `_local_ws_by_session` 부재로 가드.
        """
        for ws in list(self._user_subs.get(user_id, ())):
            sid = getattr(ws, "session_id", None)
            if sid is None or sid not in self._local_ws_by_session:
                continue  # 이미 끊긴 WS — skip
            self.register_ws_to_room(ws, room_id)


    def unsubscribe_user_from_room(self, user_id: str, room_id: str) -> None:
        """유저의 모든 로컬 세션을 방 구독에서 제거. leave / kick 시 호출.

        반드시 leave/kick 의 시스템 메시지 (`fan_out_to_room`) **이전** 에 호출 —                                                                                                                                             
        1) leak 차단 보장: send_system_message 가 실패해도 이미 구독 해제됨      
        2) UX: 퇴장 당사자는 `room_left` 이벤트만 받고 자기 퇴장 시스템 메시지는 수신 안 함                                                                                                                                   
            (카톡/슬랙/디스코드 표준 동작)  
        Redis `room_members` SREM 은 송신 경로 (`_ensure_membership`) 차단용으로
        먼저 처리되며, 이 메서드는 수신 경로 (`_room_subs`) 차단용으로 별도 동작.

        오프라인 유저는 `_user_subs.get(user_id, ())` 가 빈 set 이라 no-op.
        """
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

        # 방의 마지막 구독자가 빠졌으면 빈 set 정리 (메모리 누수 방지)
        if room_set is not None and not room_set:
            del self._room_subs[room_id]


    # ──────────────────── Fan-out ────────────────────

    async def fan_out_to_room(self, room_id: str, payload: dict) -> None:
        """방의 활성 WS 전체에 브로드캐스트. 발신 세션은 서버에서 skip.

        `sender_session_id` 필드가 payload 에 있어야 발신자 본인의 WS 가 자기 메시지를
        중복 수신하지 않는다. message.new / message.updated / read / 시스템 메시지 등
        room-scoped 이벤트 공용.
        """
        sender_sid = payload.get("sender_session_id")
        recipients = [
            ws for ws in self._room_subs.get(room_id, ())
            if ws.session_id != sender_sid
        ]
        await self._broadcast(recipients, payload)


    async def fan_out_to_user(self, user_id: str, payload: dict) -> None:
        """유저의 모든 세션에 브로드캐스트 (`room_joined` / `unread_synced` 등 user-scoped)."""
        recipients = list(self._user_subs.get(user_id, ()))
        await self._broadcast(recipients, payload)


    async def fan_out_to_session(self, session_id: str, payload: dict) -> None:
        """특정 세션 직송 (`session_revoked` / 메시지 ACK 등 session-scoped).

        같은 노드에 해당 세션이 없으면 조용히 무시 — 이미 close 된 상태로 간주.
        """
        ws = self._local_ws_by_session.get(session_id)
        if ws is None:
            return
        await self._broadcast([ws], payload)


    # ──────────────────── 내부 ────────────────────

    @staticmethod
    async def _broadcast(recipients: list[WebSocket], payload: dict) -> None:
        """여러 WS 에 동시 push — 한 WS 실패가 다른 WS 를 막지 않도록 `gather(return_exceptions=True)`."""
        if not recipients:
            return
        results = await asyncio.gather(
            *(ws.send_json(payload) for ws in recipients),
            return_exceptions=True,
        )
        # 실패한 소켓 경고 로그 (메트릭 Phase 3 에서 추가)
        for ws, result in zip(recipients, results):
            if isinstance(result, Exception):
                logger.warning(
                    "fan-out send 실패: session_id={}, err={}",
                    getattr(ws, "session_id", "?"),
                    type(result).__name__,
                )
