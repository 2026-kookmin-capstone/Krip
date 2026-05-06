"""피드 팝업 라우터 Pydantic 스키마.

`OtherUserProfileResponse` 와 동일한 5개 필드 + nested feed section. plan §5.4 의
`{ ..., "feed": { "items": [...] } }` 구조를 따른다 — 더보기 페이지네이션은 클라이언트가
일반 `GET /feed/users/{user_id}` endpoint 로 분기 (popup 자체는 next_cursor 미제공).

필드 복제 (auth schema 와 5종 중복) 는 도메인 자율성 우선. auth 의 nationality 등이 변경
되면 두 곳 모두 갱신 필요 — small cost, 도메인 결합 회피 이득이 크다.
"""
from typing import List, Optional
from pydantic import BaseModel, Field

from app.domain.feed.schema.feed_post import FeedPostResponse
from app.domain.auth.model.user_travel_style import TravelStyle


class PopupFeedSection(BaseModel):
    """팝업의 피드 영역 — 최근 N개 (default 9). next_cursor 미제공."""
    items: List[FeedPostResponse] = Field(
        ..., description="최근 피드 (최신순, 최대 9개). 더보기는 일반 endpoint 로 분기.",
    )


class FeedPopupResponse(BaseModel):
    """다른 유저 프로필 미리보기 응답 — 프로필 5종 + 최근 피드 9개 합성."""
    user_id: str = Field(
        ...,
        description="유저 고유 ID",
        examples=["USER_1712345678_abc12345"],
    )
    user_name: str = Field(
        ...,
        description="사용자 이름",
        examples=["조현상"],
    )
    nationality: str = Field(
        ...,
        description="국적",
        examples=["korea"],
    )
    travel_styles: List[TravelStyle] = Field(
        ...,
        description="여행 스타일 목록",
        examples=[["activity", "food"]],
    )
    profile_image_url: Optional[str] = Field(
        None,
        description="프로필 이미지 URL (없으면 null)",
        examples=["https://cdn.example.com/profile/abc.jpg"],
    )
    feed: PopupFeedSection = Field(
        ...,
        description="최근 피드 (최대 9개). 더보기는 GET /feed/users/{user_id} 호출.",
    )
