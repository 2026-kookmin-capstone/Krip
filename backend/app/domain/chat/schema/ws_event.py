"""WebSocket 이벤트 스키마 — Pydantic v2 discriminated union 2종.

**규약**
- **클라 → 서버 요청** 은 `op` (동사) — `send` / `refresh` / ... (Phase 2 에서 read/edit/delete 추가)
- **서버 → 클라 이벤트** 는 `type` (명사) — `message.new` / `session_revoked` / ...

두 discriminator 는 **서로 다른 필드명** 을 사용한다. 같은 필드명을 공유하면 union 해상이
불가능하고 클라/서버 양쪽에서 혼란을 초래하므로 반드시 분리.

파싱 예:
    ```python
    from pydantic import TypeAdapter
    req = TypeAdapter(ClientRequest).validate_python(raw_dict)
    ```
"""
from typing import Annotated, Any, Literal, Optional, Union
from pydantic import BaseModel, Field
from datetime import datetime

from app.domain.chat.model.chat_message import MessageType


# ════════════════════════════════════════════════════════════════════
# 클라 → 서버 요청 (`op` discriminator)
# ════════════════════════════════════════════════════════════════════

class SendOp(BaseModel):
    """메시지 송신 요청."""
    op: Literal["send"]
    room_id: str = Field(..., description="보낼 방 ID")
    client_msg_id: str = Field(
        ..., description="클라 생성 UUID — 동일 ID 재전송 시 dedupe 로 차단됨"
    )
    type: MessageType = Field(MessageType.TEXT, description="메시지 종류")
    content: str = Field(..., max_length=2000, description="본문 (text 2000자 제한)")


class RefreshOp(BaseModel):
    """JWT access 토큰 갱신 요청."""
    op: Literal["refresh"]
    token: str = Field(..., description="새 access token")


ClientRequest = Annotated[
    Union[SendOp, RefreshOp],
    Field(discriminator="op"),
]


# ════════════════════════════════════════════════════════════════════
# 서버 → 클라 이벤트 (`type` discriminator)
# ════════════════════════════════════════════════════════════════════

class ConnectedEvent(BaseModel):
    """WS 연결 직후 서버가 첫 번째로 내려주는 세션 정보."""
    type: Literal["connected"]
    session_id: str = Field(..., description="서버가 발급한 세션 ID")


class MessageSentEvent(BaseModel):
    """송신한 메시지의 서버 확정 ACK — 발신 세션에만 직송."""
    type: Literal["message.sent"]
    client_msg_id: str = Field(..., description="요청 시 넘긴 client_msg_id")
    message_id: str = Field(..., description="MongoDB _id")
    server_seq: int = Field(..., description="방 내부 단조 시퀀스")
    created_at: datetime = Field(..., description="서버 확정 시각")


class MessageBody(BaseModel):
    """`message.new` 이벤트에 실리는 메시지 본문 — MongoDB 문서 스키마와 동일."""
    message_id: str
    chat_room_id: str
    server_seq: int
    sender_id: Optional[str] = None
    type: str
    content: Any
    created_at: datetime


class MessageNewEvent(BaseModel):
    """다른 세션이 방에 새 메시지를 발행했을 때 수신."""
    type: Literal["message.new"]
    sender_session_id: str = Field(
        ..., description="발신 세션 ID — 수신 측 서버에서 자기 세션 skip 필터에 사용"
    )
    message: MessageBody = Field(..., description="본문")


class SessionRevokedEvent(BaseModel):
    """특정 session_id 가 강제 종료됨 — 자기 session 이면 close(4001)."""
    type: Literal["session_revoked"]
    session_id: str = Field(..., description="종료 대상 세션 ID")


class AuthExpiredEvent(BaseModel):
    """JWT refresh 실패 / `sess:*` 부재 — 클라는 재로그인 플로우로."""
    type: Literal["auth_expired"]


class ServerErrorEvent(BaseModel):
    """일시적 서버 에러 — 클라는 backoff 후 재접속(1012)."""
    type: Literal["server_error"]
    reason: Optional[str] = Field(None, description="디버깅용 사유 (내부 로그와 매칭)")


class ServerRestartEvent(BaseModel):
    """노드 graceful shutdown 알림 — 클라 3~5s backoff 후 재접속."""
    type: Literal["server_restart"]


class RoomJoinedEvent(BaseModel):
    """방이 새로 생성되었거나 초대됨 — WS 의 로컬 dict 에 해당 방 등록."""
    type: Literal["room_joined"]
    room_id: str = Field(..., description="참여할 방 ID")


class UnreadSyncedEvent(BaseModel):
    """WS 연결 직후 백그라운드 `recover_unread_for_user` 가 끝나면 내려주는 카운트 동기화."""
    type: Literal["unread_synced"]
    counts: dict[str, int] = Field(
        ..., description="{room_id: unread_count}. 값은 0..999 범위 (999+ 캡)"
    )


ServerEvent = Annotated[
    Union[
        ConnectedEvent,
        MessageSentEvent,
        MessageNewEvent,
        SessionRevokedEvent,
        AuthExpiredEvent,
        ServerErrorEvent,
        ServerRestartEvent,
        RoomJoinedEvent,
        UnreadSyncedEvent,
    ],
    Field(discriminator="type"),
]
