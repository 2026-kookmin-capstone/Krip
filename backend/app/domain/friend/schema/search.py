from typing import List, Optional
from pydantic import BaseModel, Field

from app.domain.friend.model.friendship import FriendshipStatus
from app.domain.auth.model.user_travel_style import TravelStyle


class FriendSearchItemResponse(BaseModel):
    user_id: str = Field(..., description="유저 고유 ID — 친구 요청 / 채팅 연결에 사용")
    user_name: str = Field(..., description="검색 결과에 표시할 이름")
    profile_image_url: Optional[str] = Field(None, description="프로필 이미지 URL (없으면 null)")
    nationality: str = Field(..., description="국적 코드")
    travel_styles: List[TravelStyle] = Field(..., description="여행 스타일 목록")
    friendship_status: Optional[FriendshipStatus] = Field(
        None, description="친구 상태 (pending / accepted / rejected, 관계 없으면 null)"
    )
    is_requester: Optional[bool] = Field(
        None, description="pending 상태일 때 내가 요청자인지 여부 (그 외 null)"
    )
    i_blocked_peer: bool = Field(
        ..., description="내가 상대를 차단했는지 — 검색은 차단 유저 자동 제외이므로 항상 false"
    )


class FriendSearchListResponse(BaseModel):
    items: List[FriendSearchItemResponse] = Field(..., description="검색 결과")
    next_cursor: Optional[str] = Field(None, description="다음 페이지 커서 (마지막 페이지면 null)")
