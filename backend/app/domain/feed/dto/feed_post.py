"""피드 게시물 DTO — 서비스 → 라우터 경계.

서비스가 SQLAlchemy 모델 (`FeedPost`) 을 직접 반환하지 않고 DTO 로 변환해 노출한다.
DB 스키마 변경이 API 계약을 깨지 않게 분리.
"""
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

from app.domain.feed.model.feed_post import FeedVisibility


@dataclass
class FeedPostData:
    """피드 게시물 단건 응답 DTO."""
    post_id: str
    user_id: str
    visibility: FeedVisibility
    caption: Optional[str]
    original_url: str
    thumbnail_small_url: str
    thumbnail_medium_url: str
    created_at: datetime
    updated_at: datetime


@dataclass
class FeedPostListData:
    """피드 게시물 목록 응답 DTO (커서 페이지네이션)."""
    posts: List[FeedPostData]
    next_cursor: Optional[str]
