from typing import List, Optional
from pymongo import IndexModel
from pydantic import BaseModel, Field
from beanie import Document, Indexed


# ──────────────────── Embedded Models ────────────────────


class PlaceLocation(BaseModel):
    """GeoJSON Point 형식의 좌표

    - MongoDB 2dsphere 인덱스를 위해 GeoJSON 표준 사용
    - coordinates: [경도(lng), 위도(lat)] 순서 (GeoJSON 표준)
    """

    type: str = Field(default="Point", description="GeoJSON 타입")
    coordinates: List[float] = Field(
        ..., description="[경도, 위도] 좌표 (GeoJSON 표준)"
    )


class PlacePriceRange(BaseModel):
    """가격 범위 (KRW)"""

    min: Optional[str] = Field(None, description="최소 가격 (예: '10000 KRW')")
    max: Optional[str] = Field(None, description="최대 가격 (예: '20000 KRW')")


class PlaceReview(BaseModel):
    """Google Places 리뷰"""

    author: str = Field(..., description="리뷰 작성자")
    rating: Optional[int] = Field(None, description="별점 (1~5)")
    relative_time: Optional[str] = Field(None, description="작성 시점 (예: '8달 전')")
    text: Optional[str] = Field(None, description="리뷰 본문")


# ──────────────────── Document Model ────────────────────


class Place(Document):
    """서울 관광 장소 (MongoDB)

    - Google Places 기반 서울 장소 데이터 28,309건
    - place_id 기준 중복 제거 완료
    - location은 GeoJSON Point로 저장하여 근처 장소 검색 지원
    """

    # ── 식별 ──
    place_id: Indexed(str, unique=True) = Field(..., description="Google Places 고유 ID")  # type: ignore

    # ── 기본 정보 ──
    display_name: str = Field(..., description="장소 이름")
    category: Indexed(str) = Field(..., description="한글 카테고리명 (예: '한식당')")  # type: ignore
    types: List[str] = Field(default_factory=list, description="Google Places 타입 태그")
    address: str = Field(..., description="전체 주소")
    short_address: Optional[str] = Field(None, description="간략 주소 (예: '중구 을지로 264')")

    # ── 위치 (GeoJSON) ──
    location: PlaceLocation = Field(..., description="GeoJSON Point 좌표")

    # ── 평가 ──
    rating: Optional[float] = Field(None, description="평균 별점 (1.0~5.0)")
    rating_count: Optional[int] = Field(None, description="리뷰 수")
    price_level: Optional[str] = Field(None, description="가격 수준 (예: '보통 ($$)')")
    price_range: Optional[PlacePriceRange] = Field(None, description="가격 범위 (KRW)")

    # ── 요약 ──
    editorial_summary: Optional[str] = Field(None, description="Google 편집자 요약")
    generative_summary: Optional[str] = Field(None, description="AI 생성 요약")
    review_summary: Optional[str] = Field(None, description="리뷰 요약")

    # ── 연락처 ──
    phone: Optional[str] = Field(None, description="국내 전화번호")
    phone_international: Optional[str] = Field(None, description="국제 전화번호")
    website: Optional[str] = Field(None, description="웹사이트 URL")
    google_maps_url: Optional[str] = Field(None, description="Google Maps 장소 페이지 URL")
    google_map_review_link: Optional[str] = Field(None, description="Google Maps 리뷰 페이지 URL")

    # ── 운영 정보 ──
    opening_hours: Optional[List[str]] = Field(None, description="요일별 영업시간")
    services: Optional[List[str]] = Field(None, description="제공 서비스 (예: '매장식사', '배달')")
    payment: Optional[List[str]] = Field(None, description="결제 수단 (예: '신용카드', 'NFC')")
    accessibility: Optional[List[str]] = Field(None, description="접근성 정보")
    parking: Optional[List[str]] = Field(None, description="주차 정보")

    # ── 리뷰 ──
    reviews: List[PlaceReview] = Field(default_factory=list, description="Google Places 리뷰 목록")

    # ── 사진 (현재 미사용, 빈 배열로 저장) ──
    photos: List[str] = Field(default_factory=list, description="사진 URL 목록")

    class Settings:
        name = "place"  # MongoDB 컬렉션명
        # $geoNear 쿼리는 2dsphere 인덱스가 반드시 필요. init_beanie 시점에 자동 생성/idempotent.
        indexes = [
            IndexModel([("location", "2dsphere")], name="location_2dsphere"),
        ]
