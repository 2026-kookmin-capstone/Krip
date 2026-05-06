"""피드 댓글 DTO — 서비스 → 라우터 경계.

서비스가 SQLAlchemy 모델 직접 노출 대신 DTO 변환. DB 스키마 변경이 API 계약을 깨지 않게 분리.
"""
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class FeedPostCommentData:
    """댓글 단건 응답 DTO."""
    comment_id: str
    post_id: str
    user_id: str
    content: str
    created_at: datetime
    updated_at: datetime


@dataclass
class FeedPostCommentListData:
    """댓글 목록 응답 DTO (커서 페이지네이션, 최신순)."""
    comments: List[FeedPostCommentData]
    next_cursor: Optional[str]
