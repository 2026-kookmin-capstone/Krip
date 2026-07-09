from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ──────────────────── Response ────────────────────

class ChatMessageResponse(BaseModel):
    message_id: str = Field(..., description="메시지 ID (MongoDB _id)")
    chat_room_id: str = Field(..., description="방 ID")
    server_seq: int = Field(..., description="방 내부 단조 시퀀스 — 페이징/읽음 계산 기준")
    sender_id: Optional[str] = Field(None, description="보낸 유저 ID (시스템 메시지면 null)")
    type: str = Field(..., description="메시지 종류 (text / image / file / system)")
    content: Optional[Any] = Field(
        None,
        description=(
            "본문 — type 에 따라 다름. text=str, image/file=dict, system=object, "
            "삭제된 메시지는 null"
        ),
    )
    created_at: datetime = Field(..., description="보낸 시각")
    edited_at: Optional[datetime] = Field(None, description="마지막 편집 시각 (없으면 null)")
    deleted_at: Optional[datetime] = Field(None, description="삭제 시각 (없으면 null)")


class MessageHistoryResponse(BaseModel):
    messages: List[ChatMessageResponse] = Field(..., description="메시지 배열 — 정렬 방향은 쿼리 방식에 따름")
    has_more: bool = Field(..., description="다음 페이지 존재 여부")
    next_cursor: Optional[int] = Field(
        None,
        description=(
            "다음 호출 시 `before_server_seq` 또는 `after_server_seq` 로 그대로 사용할 "
            "값 (= messages[-1].server_seq). has_more=false 면 null"
        ),
    )


# ──────────────────── 편집 ────────────────────

class EditMessageBody(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {"content": "수정된 본문입니다."},
        }
    )

    content: str = Field(..., min_length=1, max_length=2000, description="새 본문")


class EditMessageResponse(BaseModel):
    message_id: str
    content: Any
    edited_at: datetime
