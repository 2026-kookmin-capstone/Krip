from typing import List, Optional
from pydantic import Field
from datetime import date, datetime, timezone
from beanie import Document, Indexed


class TripmatePostDraft(Document):
    """여행 메이트 게시글 임시저장 (MongoDB)

    - 유저당 1개만 유지 (user_id unique index)
    - 프론트에서 30초마다 자동 저장
    """

    user_id: Indexed(str, unique=True) = Field(..., description="작성자 ID")  # type: ignore
    title: Optional[str] = Field(None, description="게시글 제목")
    content: Optional[str] = Field(None, description="게시글 내용")
    preferred_age_min: Optional[int] = Field(None, description="선호 나이 하한")
    preferred_age_max: Optional[int] = Field(None, description="선호 나이 상한")
    preferred_gender: Optional[str] = Field(None, description="선호 성별 (male / female / any)")
    region: Optional[str] = Field(None, description="여행 지역")
    travel_start_date: Optional[date] = Field(None, description="여행 시작일")
    travel_end_date: Optional[date] = Field(None, description="여행 종료일")
    companion_type: Optional[str] = Field(None, description="동행 타입 (friend / family / couple / sole)")
    image_urls: List[str] = Field(default_factory=list, description="업로드된 이미지 URL 목록")
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc), description="마지막 임시저장 시각")

    class Settings:
        name = "tripmate_post_draft"  # MongoDB 컬렉션명
