from typing import List, Optional
from dataclasses import dataclass

from app.domain.friend.model.friendship import FriendshipStatus
from app.domain.auth.model.user_travel_style import TravelStyle


@dataclass
class FriendSearchData:
    """친구 추가 화면 검색 결과 단건 DTO.

    민감 정보(나이/성별/이메일/전화번호)는 포함하지 않는다 — 검색은 친구 후보 식별 용도.
    """
    user_id: str
    user_name: str
    nationality: str
    travel_styles: List[TravelStyle]
    friendship_status: Optional[FriendshipStatus]   # 관계 없으면 None
    is_requester: Optional[bool]                    # PENDING 일 때만 의미, 그 외 None
    i_blocked_peer: bool                            # 검색은 차단 유저 자동 제외 → 항상 False
    profile_image_url: Optional[str] = None


@dataclass
class FriendSearchListData:
    """친구 검색 목록 응답 DTO (커서 페이지네이션)"""
    items: List[FriendSearchData]
    next_cursor: Optional[str]
