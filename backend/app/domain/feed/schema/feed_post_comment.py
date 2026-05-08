"""피드 게시물 댓글 라우터 Pydantic 스키마."""
from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime

from app.domain.feed.model.feed_post_comment import COMMENT_MAX_LENGTH


# ──────────────────── Request ────────────────────

class CreateCommentRequest(BaseModel):
    """댓글 작성 요청.

    `content` 는 1자 이상 — Pydantic `min_length` + 서비스의 strip 검증 두 단계로 빈 문자열 /
    공백만 입력을 차단. DB CHECK (`char_length(content) >= 1`) 가 마지막 방어선.
    캡션과 의미가 다름: 캡션 = "있음/없음" (빈→None 정규화), 댓글 = "추가 액션" (빈→400 reject).
    """
    content: str = Field(
        ...,
        min_length=1,
        max_length=COMMENT_MAX_LENGTH,
        description=f"댓글 본문 (1~{COMMENT_MAX_LENGTH}자, 공백만 입력 거절)",
    )


# ──────────────────── Response ────────────────────

class CommentResponse(BaseModel):
    """댓글 단건 응답 — 작성자 프로필 정보 포함.

    `user_name` / `profile_image_url` 은 repository 의 단일 JOIN 쿼리 (`feed_post_comment
    ⨝ users ⨝ user_detail_inform`) 결과로 채움. 클라이언트가 별도 batch 조회 없이 즉시 표시.
    """
    comment_id: str = Field(..., description="댓글 고유 ID")
    post_id: str = Field(..., description="대상 게시물 ID")
    user_id: str = Field(..., description="작성자 유저 ID")
    user_name: str = Field(..., description="작성자 닉네임 (detail 결손 시 빈 문자열)")
    profile_image_url: Optional[str] = Field(
        None, description="작성자 프로필 이미지 URL (없으면 null)",
    )
    content: str = Field(..., description="댓글 본문")
    created_at: datetime = Field(..., description="작성 시각")
    updated_at: datetime = Field(..., description="마지막 수정 시각")


class CommentListResponse(BaseModel):
    """댓글 목록 응답 (커서 페이지네이션, 최신순)."""
    comments: List[CommentResponse] = Field(..., description="댓글 목록 (최신순)")
    next_cursor: Optional[str] = Field(
        None,
        description="다음 페이지 커서 (마지막 댓글의 comment_id). 더 없으면 null.",
    )
