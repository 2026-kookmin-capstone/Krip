from datetime import datetime, timezone

from beanie import Document, Indexed
from pydantic import Field


class FriendSearchHistory(Document):
    """친구 추가 화면 검색 기록

    - 유저당 최대 10개까지 저장
    - 11개째 저장 시 가장 오래된 검색어 자동 삭제
    """

    user_id: Indexed(str) = Field(..., description="검색한 유저 ID")  # type: ignore
    search_name: str = Field(..., description="검색어")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="검색 시각",
    )

    class Settings:
        name = "friend_search_history"
