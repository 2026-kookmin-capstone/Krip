"""인박스 라우터 Pydantic 스키마.

`InboxItemType` / `TargetType` 는 model 의 enum 을 그대로 노출 (str enum 이라 JSON 직렬화 자연).
"""
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from app.domain.notification.model.inbox import InboxItemType, TargetType


# ──────────────────── Response ────────────────────

class InboxItemResponse(BaseModel):
    """인박스 단건 응답 — denormalized snapshot 포함.

    snapshot 필드 (`actor_name` / `actor_profile_image_url` / `target_preview` /
    `comment_preview`) 는 항목 발생 시점 값. deep link 클릭 시 클라이언트가 진짜 최신
    데이터를 별도 fetch.
    """
    inbox_item_id: str = Field(..., description="인박스 항목 고유 ID (Mongo ObjectId 의 hex string)")
    type: InboxItemType = Field(..., description="항목 종류")
    actor_id: str = Field(..., description="행위자 유저 ID")
    actor_name: str = Field(..., description="행위자 닉네임 (항목 시점 snapshot)")
    actor_profile_image_url: Optional[str] = Field(
        None, description="행위자 프로필 이미지 URL (항목 시점 snapshot)",
    )
    target_type: TargetType = Field(..., description="대상 리소스 타입 (deep link 분기)")
    target_id: str = Field(..., description="대상 리소스 ID (feed_post.post_id 등)")
    comment_id: Optional[str] = Field(
        None, description="FEED_COMMENT 인 경우 댓글 ID (deep link 앵커)",
    )
    target_preview: Optional[str] = Field(
        None, description="피드 썸네일 URL 또는 트립메이트 title (snapshot)",
    )
    comment_preview: Optional[str] = Field(
        None, description="댓글 본문 미리보기 (FEED_COMMENT 만, 100자 제한)",
    )
    is_read: bool = Field(..., description="읽음 여부")
    created_at: datetime = Field(..., description="항목 생성 시각")


class InboxListResponse(BaseModel):
    """인박스 목록 응답 (커서 페이지네이션, 최신순).

    `next_cursor` 는 마지막 항목의 `created_at` ISO 8601 string. 더 없으면 null.
    """
    items: List[InboxItemResponse] = Field(..., description="인박스 항목 목록 (최신순)")
    next_cursor: Optional[str] = Field(
        None,
        description="다음 페이지 커서 (마지막 항목의 created_at ISO string). 더 없으면 null.",
    )


class UnreadCountResponse(BaseModel):
    """미읽음 인박스 카운트 — 999+ 캡 적용."""
    unread_count: int = Field(
        ...,
        ge=0,
        description="미읽음 인박스 항목 수, 맥스 999+ 임.",
    )
