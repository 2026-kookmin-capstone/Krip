from dataclasses import dataclass
from typing import List, Optional

from app.domain.auth.model.user_detail_inform import Gender
from app.domain.auth.model.user_travel_style import TravelStyle
from app.domain.friend.model.friendship import FriendshipStatus


@dataclass
class FriendDetailData:
    """상대 유저 기본 프로필 + 내 기준 관계 상태 DTO.

    민감 정보(auth_provider, status, email, phone_number)는 포함하지 않는다.
    """

    user_id: str
    user_name: str
    age: int
    gender: Gender
    nationality: str
    travel_styles: List[TravelStyle]

    friendship_id: Optional[str]
    friendship_status: Optional[FriendshipStatus]
    is_requester: Optional[bool]
    i_blocked_peer: bool

    profile_image_url: Optional[str] = None
