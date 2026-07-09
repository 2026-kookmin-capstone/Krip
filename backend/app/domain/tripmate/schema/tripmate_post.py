from datetime import date, datetime
from typing import Annotated, List, Optional

from pydantic import BaseModel, Field, StringConstraints, model_validator

from app.domain.auth.model.user_detail_inform import Gender
from app.domain.tripmate.model.tripmate_post import CompanionType, PreferredGender


# 첨부 이미지 상한 — 무제한이면 Mongo draft 문서 팽창(수백만 URL) + 목록 조회 폭증 가능.
# 개수는 업로드 배치(10개) × 여유, URL 1건 길이는 거대 문자열 주입 차단.
_MAX_POST_IMAGES = 20
_MAX_IMAGE_URL_LEN = 2048
_ImageUrl = Annotated[str, StringConstraints(max_length=_MAX_IMAGE_URL_LEN)]


def _validate_post_ranges(model):
    """나이/여행일 범위 교차 검증 — 위반 시 DB CheckConstraint(500) 대신 422 로 매핑."""
    if model.preferred_age_min > model.preferred_age_max:
        raise ValueError("선호 나이 하한이 상한보다 클 수 없습니다.")
    if model.travel_start_date > model.travel_end_date:
        raise ValueError("여행 시작일이 종료일보다 늦을 수 없습니다.")
    return model


# ──────────────────── Request ────────────────────

class CreatePostRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100, description="게시글 제목")
    content: str = Field(..., min_length=10, max_length=500, description="게시글 내용 (10자 ~ 500자)")
    preferred_age_min: int = Field(..., ge=1, description="선호 나이 하한")
    preferred_age_max: int = Field(..., ge=1, description="선호 나이 상한")
    preferred_gender: PreferredGender = Field(..., description="선호 성별 (male / female / any)")
    region: str = Field(..., max_length=100, description="여행 지역")
    travel_start_date: date = Field(..., description="여행 시작일")
    travel_end_date: date = Field(..., description="여행 종료일")
    companion_type: CompanionType = Field(..., description="동행 타입 (friend / family / couple / sole)")
    image_urls: Optional[List[_ImageUrl]] = Field(None, max_length=_MAX_POST_IMAGES, description="첨부 이미지 URL 목록 (이미지 업로드 API로 받은 URL)")

    _validate_ranges = model_validator(mode="after")(_validate_post_ranges)

    class Config:
        json_schema_extra = {
            "example": {
                "title": "제주도 같이 가실 분!",
                "content": "7월에 제주도 2박 3일 여행 같이 가실 분 구합니다. 맛집 탐방 위주로 계획 중입니다.",
                "preferred_age_min": 20,
                "preferred_age_max": 30,
                "preferred_gender": "any",
                "region": "제주도",
                "travel_start_date": "2026-07-10",
                "travel_end_date": "2026-07-12",
                "companion_type": "friend",
                "image_urls": [],
            }
        }


class UpdatePostRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100, description="게시글 제목")
    content: str = Field(..., min_length=10, max_length=500, description="게시글 내용 (10자 ~ 500자)")
    preferred_age_min: int = Field(..., ge=1, description="선호 나이 하한")
    preferred_age_max: int = Field(..., ge=1, description="선호 나이 상한")
    preferred_gender: PreferredGender = Field(..., description="선호 성별 (male / female / any)")
    region: str = Field(..., max_length=100, description="여행 지역")
    travel_start_date: date = Field(..., description="여행 시작일")
    travel_end_date: date = Field(..., description="여행 종료일")
    companion_type: CompanionType = Field(..., description="동행 타입 (friend / family / couple / sole)")
    image_urls: Optional[List[_ImageUrl]] = Field(None, max_length=_MAX_POST_IMAGES, description="첨부 이미지 URL 목록 (이미지 업로드 API로 받은 URL)")

    _validate_ranges = model_validator(mode="after")(_validate_post_ranges)


# ──────────────────── Response ────────────────────

class AuthorResponse(BaseModel):
    user_name: str = Field(..., description="작성자 닉네임")
    age: int = Field(..., description="작성자 나이")
    gender: Gender = Field(..., description="작성자 성별 (male / female)")
    nationality: str = Field(..., description="작성자 국적")


class PostCreateResponse(BaseModel):
    post_id: str = Field(..., description="게시글 고유 ID")
    user_id: str = Field(..., description="작성자 ID")
    title: str = Field(..., description="게시글 제목")
    content: str = Field(..., description="게시글 내용")
    preferred_age_min: int = Field(..., description="선호 나이 하한")
    preferred_age_max: int = Field(..., description="선호 나이 상한")
    preferred_gender: PreferredGender = Field(..., description="선호 성별")
    region: str = Field(..., description="여행 지역")
    travel_start_date: date = Field(..., description="여행 시작일")
    travel_end_date: date = Field(..., description="여행 종료일")
    companion_type: CompanionType = Field(..., description="동행 타입")
    is_displayed: bool = Field(..., description="게시글 표시 여부")
    created_at: datetime = Field(..., description="게시글 작성일")
    updated_at: datetime = Field(..., description="게시글 수정일")
    image_urls: List[str] = Field(..., description="첨부 이미지 URL 목록")
    profile_image_url: Optional[str] = Field(None, description="작성자 프로필 이미지 URL (없으면 null)")


class PostDetailResponse(BaseModel):
    post_id: str = Field(..., description="게시글 고유 ID")
    user_id: str = Field(..., description="작성자 ID")
    author: AuthorResponse = Field(..., description="작성자 프로필 정보")
    title: str = Field(..., description="게시글 제목")
    content: str = Field(..., description="게시글 내용")
    preferred_age_min: int = Field(..., description="선호 나이 하한")
    preferred_age_max: int = Field(..., description="선호 나이 상한")
    preferred_gender: PreferredGender = Field(..., description="선호 성별")
    region: str = Field(..., description="여행 지역")
    travel_start_date: date = Field(..., description="여행 시작일")
    travel_end_date: date = Field(..., description="여행 종료일")
    companion_type: CompanionType = Field(..., description="동행 타입")
    is_displayed: bool = Field(..., description="게시글 표시 여부")
    created_at: datetime = Field(..., description="게시글 작성일")
    updated_at: datetime = Field(..., description="게시글 수정일")
    like_count: int = Field(..., description="좋아요 수")
    is_liked: bool = Field(..., description="현재 유저의 좋아요 여부")
    image_urls: List[str] = Field(..., description="첨부 이미지 URL 목록")
    profile_image_url: Optional[str] = Field(None, description="작성자 프로필 이미지 URL (없으면 null)")


class PostListResponse(BaseModel):
    posts: List[PostDetailResponse] = Field(..., description="게시글 목록")
    next_cursor: Optional[str] = Field(None, description="다음 페이지 커서 (마지막 페이지면 null)")


class ToggleDisplayResponse(BaseModel):
    post_id: str = Field(..., description="게시글 고유 ID")
    is_displayed: bool = Field(..., description="변경된 표시 여부")


class LikeResponse(BaseModel):
    post_id: str = Field(..., description="게시글 고유 ID")
    like_count: int = Field(..., description="현재 좋아요 수")


class LikedUsersResponse(BaseModel):
    post_id: str = Field(..., description="게시글 고유 ID")
    user_ids: List[str] = Field(..., description="좋아요 누른 유저 ID 목록")


# ──────────────────── Draft (임시저장) ────────────────────

class SaveDraftRequest(BaseModel):
    title: Optional[str] = Field(None, max_length=100, description="게시글 제목")
    content: Optional[str] = Field(None, max_length=500, description="게시글 내용")
    preferred_age_min: Optional[int] = Field(None, ge=1, description="선호 나이 하한")
    preferred_age_max: Optional[int] = Field(None, ge=1, description="선호 나이 상한")
    preferred_gender: Optional[str] = Field(None, description="선호 성별 (male / female / any)")
    region: Optional[str] = Field(None, max_length=100, description="여행 지역")
    travel_start_date: Optional[date] = Field(None, description="여행 시작일")
    travel_end_date: Optional[date] = Field(None, description="여행 종료일")
    companion_type: Optional[str] = Field(None, description="동행 타입 (friend / family / couple / sole)")
    image_urls: Optional[List[_ImageUrl]] = Field(None, max_length=_MAX_POST_IMAGES, description="첨부 이미지 URL 목록")


class DraftResponse(BaseModel):
    user_id: str = Field(..., description="작성자 ID")
    title: Optional[str] = Field(None, description="게시글 제목")
    content: Optional[str] = Field(None, description="게시글 내용")
    preferred_age_min: Optional[int] = Field(None, description="선호 나이 하한")
    preferred_age_max: Optional[int] = Field(None, description="선호 나이 상한")
    preferred_gender: Optional[str] = Field(None, description="선호 성별")
    region: Optional[str] = Field(None, description="여행 지역")
    travel_start_date: Optional[date] = Field(None, description="여행 시작일")
    travel_end_date: Optional[date] = Field(None, description="여행 종료일")
    companion_type: Optional[str] = Field(None, description="동행 타입")
    image_urls: List[str] = Field(default_factory=list, description="첨부 이미지 URL 목록")
    updated_at: datetime = Field(..., description="마지막 임시저장 시각")
