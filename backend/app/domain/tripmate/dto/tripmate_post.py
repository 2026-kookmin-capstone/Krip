from typing import List, Optional
from dataclasses import dataclass
from datetime import date, datetime

from app.domain.tripmate.model.tripmate_post import PreferredGender, CompanionType


@dataclass
class TripmatePostData:
    """게시글 단건 응답 DTO"""
    post_id: str
    user_id: str
    title: str
    content: str
    preferred_age_min: int
    preferred_age_max: int
    preferred_gender: PreferredGender
    region: str
    travel_start_date: date
    travel_end_date: date
    companion_type: CompanionType
    is_displayed: bool
    created_at: datetime
    updated_at: datetime
    like_count: int
    is_liked: bool
    image_urls: List[str]


@dataclass
class TripmatePostListData:
    """게시글 목록 응답 DTO (커서 페이지네이션)"""
    posts: List[TripmatePostData]
    next_cursor: Optional[str]
