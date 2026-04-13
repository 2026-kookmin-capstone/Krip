from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends, Request
from dependency_injector.wiring import Provide, inject

from app.domain.tour.service.place import PlaceService
from app.domain.tour.schema.place import (
    PlaceResponse,
    PlaceListResponse,
    PlaceLocationResponse,
    PlacePriceRangeResponse,
    PlaceReviewResponse,
)
from app.core.logger import get_logger
from app.container import Container


router = APIRouter(prefix="/places", tags=["관광 장소"])
logger = get_logger("tour.place")

# 기본 좌표 (서울 광화문)
DEFAULT_LAT = 37.57594
DEFAULT_LNG = 126.97688


# ──────────────────── 장소 조회 ────────────────────


@router.get("")
@inject
async def get_places(
    request: Request,
    lat: Optional[float] = Query(None, description="위도 (미입력 시 광화문 기준)"),
    lng: Optional[float] = Query(None, description="경도 (미입력 시 광화문 기준)"),
    keyword: Optional[str] = Query(None, min_length=1, description="검색 키워드 (장소명, 카테고리)"),
    cursor: Optional[str] = Query(None, description="다음 페이지 커서"),
    max_distance: Optional[float] = Query(None, gt=0, description="최대 검색 반경 (미터)"),
    place_service: PlaceService = Depends(Provide[Container.place_service]),
) -> PlaceListResponse:
    """장소 조회 (거리순, 30개 페이지네이션)

    - 위도/경도 미입력 시 서울 광화문 기준
    - keyword 입력 시 장소명·카테고리 검색, 미입력 시 전체 조회
    - 로그인 유저의 즐겨찾기 여부 포함
    """
    actual_lat = lat if lat is not None else DEFAULT_LAT
    actual_lng = lng if lng is not None else DEFAULT_LNG
    user_id: str = request.state.user_id

    try:
        if keyword:
            result = await place_service.search_nearby_places(
                lat=actual_lat,
                lng=actual_lng,
                keyword=keyword,
                cursor=cursor,
                max_distance=max_distance,
                user_id=user_id,
            )
        else:
            result = await place_service.get_nearby_places(
                lat=actual_lat,
                lng=actual_lng,
                cursor=cursor,
                max_distance=max_distance,
                user_id=user_id,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("장소 조회 실패: %s", e)
        raise HTTPException(status_code=500, detail="장소 조회에 실패했습니다.")

    return PlaceListResponse(
        places=[_to_place_response(p) for p in result.places],
        next_cursor=result.next_cursor,
    )


# ──────────────────── 내부 변환 유틸 ────────────────────


def _to_place_response(place) -> PlaceResponse:
    """PlaceData DTO → PlaceResponse 스키마 변환"""
    return PlaceResponse(
        place_id=place.place_id,
        display_name=place.display_name,
        category=place.category,
        types=place.types,
        address=place.address,
        short_address=place.short_address,
        location=PlaceLocationResponse(lat=place.location.lat, lng=place.location.lng),
        rating=place.rating,
        rating_count=place.rating_count,
        price_level=place.price_level,
        price_range=PlacePriceRangeResponse(
            min=place.price_range.min, max=place.price_range.max
        ) if place.price_range else None,
        editorial_summary=place.editorial_summary,
        generative_summary=place.generative_summary,
        review_summary=place.review_summary,
        phone=place.phone,
        phone_international=place.phone_international,
        website=place.website,
        google_maps_url=place.google_maps_url,
        google_map_review_link=place.google_map_review_link,
        opening_hours=place.opening_hours,
        services=place.services,
        payment=place.payment,
        accessibility=place.accessibility,
        parking=place.parking,
        reviews=[
            PlaceReviewResponse(
                author=r.author,
                rating=r.rating,
                relative_time=r.relative_time,
                text=r.text,
            )
            for r in place.reviews
        ],
        distance=place.distance,
        is_favorite=place.is_favorite,
    )
