from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.core.ai.tour_planner.load import TourPlanner
from app.core.logger import get_logger


router = APIRouter(prefix="/recommend", tags=["여행 추천"])
logger = get_logger("tour.recommend")


# ──────────────────── Request / Response ────────────────────


class TourRecommendRequest(BaseModel):
    travel_days: int = Field(..., ge=1, le=10, description="여행 일수 (1~10)")
    travel_style: str = Field(..., description="여행 스타일 (맛집 탐방, 쇼핑, 문화/역사, 카페/힙플레이스, 자연/공원)")
    budget: str = Field(..., description="여행 예산 (저예산, 중간, 고예산)")
    companion_type: str = Field(..., description="동행 유형 (혼자, 연인, 친구, 가족)")
    schedule_density: str = Field(..., description="선호 일정 밀도 (빽빽하게, 보통, 널널하게)")


class TourPlaceLocationResponse(BaseModel):
    lat: float = Field(..., description="위도")
    lng: float = Field(..., description="경도")


class TourPlaceResponse(BaseModel):
    place_id: str = Field(..., description="Google Places 고유 ID")
    display_name: str = Field(..., description="장소 이름")
    category: str = Field(..., description="카테고리")
    address: str = Field(..., description="주소")
    location: TourPlaceLocationResponse = Field(..., description="좌표")
    rating: Optional[float] = Field(None, description="평균 별점")
    description: str = Field(..., description="추천 이유와 특징")
    tip: str = Field(..., description="방문 팁")


class TourDayResponse(BaseModel):
    day: int = Field(..., description="여행 일차")
    cluster_name: str = Field(..., description="권역 이름")
    places: List[TourPlaceResponse] = Field(..., description="여행 장소 목록")


class TourRecommendResponse(BaseModel):
    tour_plan: List[TourDayResponse] = Field(..., description="일자별 여행 플랜")


# ──────────────────── API ────────────────────


@router.post("", status_code=200)
async def recommend_tour(body: TourRecommendRequest) -> TourRecommendResponse:
    """사용자 맞춤 서울 여행 코스 추천

    - 여행 일수, 스타일, 예산, 동행 유형, 일정 밀도를 기반으로 최적 코스 생성
    - 일자별 권역과 실제 장소(place_id 포함)를 반환
    """
    tour_planner = TourPlanner()

    try:
        result = await tour_planner.invoke(
            travel_days=body.travel_days,
            travel_style=body.travel_style,
            budget=body.budget,
            companion_type=body.companion_type,
            schedule_density=body.schedule_density,
        )
    except Exception as e:
        logger.error("여행 추천 실패: {}", e)
        raise HTTPException(status_code=500, detail="여행 추천에 실패했습니다.")

    return TourRecommendResponse(
        tour_plan=[
            TourDayResponse(
                day=day.day,
                cluster_name=day.cluster_name,
                places=[
                    TourPlaceResponse(
                        place_id=p.place_id,
                        display_name=p.display_name,
                        category=p.category,
                        address=p.address,
                        location=TourPlaceLocationResponse(
                            lat=p.location.lat,
                            lng=p.location.lng,
                        ),
                        rating=p.rating,
                        description=p.description,
                        tip=p.tip,
                    )
                    for p in day.places
                ],
            )
            for day in result.tour_plan
        ],
    )
