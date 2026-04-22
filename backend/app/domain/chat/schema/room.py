from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from app.domain.chat.model.chat_room import ChatRoomType


# ──────────────────── Request ────────────────────

class CreateDirectRoomBody(BaseModel):
    peer_user_id: str = Field(..., description="대화할 상대 유저 ID")

    class Config:
        json_schema_extra = {
            "example": {
                "peer_user_id": "USER_1700000000_abcdef12",
            }
        }


# ──────────────────── Response — 내부 구성요소 ────────────────────

class ChatRoomPeerResponse(BaseModel):
    """1:1 방 상대방 프로필. 탈퇴한 경우 필드가 모두 null — 클라는 '탈퇴한 사용자' 로 표시."""
    user_id: Optional[str] = Field(None, description="상대 유저 ID (탈퇴 시 null)")
    user_name: Optional[str] = Field(None, description="상대 닉네임 (탈퇴 시 null)")


class LastMessagePreviewResponse(BaseModel):
    """방 리스트 미리보기용 최신 메시지 요약."""
    message_id: str = Field(..., description="메시지 ID (MongoDB _id)")
    server_seq: int = Field(..., description="방 내부 단조 시퀀스")
    sender_id: Optional[str] = Field(None, description="보낸 유저 ID (시스템 메시지면 null)")
    type: str = Field(..., description="메시지 종류 (text / image / file / system)")
    content: Optional[str] = Field(None, description="미리보기 본문 (삭제된 메시지는 null)")
    created_at: datetime = Field(..., description="보낸 시각")


# ──────────────────── Response — 방 본체 ────────────────────

class ChatRoomResponse(BaseModel):
    chat_room_id: str = Field(..., description="방 고유 ID")
    type: ChatRoomType = Field(..., description="방 종류 (direct / group)")
    title: Optional[str] = Field(None, description="방 제목 (그룹방만, direct 는 null)")
    peer: Optional[ChatRoomPeerResponse] = Field(
        None, description="1:1 방의 상대방 프로필 (group 은 null)"
    )
    last_message: Optional[LastMessagePreviewResponse] = Field(
        None, description="최신 메시지 미리보기 (신규 방은 null)"
    )
    unread_count: int = Field(..., description="현재 유저의 미읽음 메시지 수")
    last_message_at: Optional[datetime] = Field(None, description="최신 메시지 시각")
    effective_last_at: datetime = Field(
        ..., description="정렬 기준 시각 — last_message_at 없으면 created_at 으로 fallback"
    )


class ChatRoomListResponse(BaseModel):
    items: List[ChatRoomResponse] = Field(..., description="방 리스트")
    next_cursor: Optional[str] = Field(
        None, description="다음 페이지 커서 (마지막 페이지면 null). Phase 1 은 항상 null"
    )
