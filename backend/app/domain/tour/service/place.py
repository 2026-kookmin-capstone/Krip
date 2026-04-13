from typing import Optional

from app.domain.tour.repository.place import PlaceRepository, PAGE_SIZE
from app.domain.tour.dto.place import (
    PlaceData,
    PlaceListData,
    PlaceLocationData,
    PlacePriceRangeData,
    PlaceReviewData,
)


class PlaceService:
    def __init__(self):
        self.place_repo = PlaceRepository()

    # ──────────────────── 거리순 장소 조회 ────────────────────

    async def get_nearby_places(
        self,
        lat: float,
        lng: float,
        cursor: Optional[str] = None,
        max_distance: Optional[float] = None,
    ) -> PlaceListData:
        """현재 위치 기준 가까운 장소 목록 조회 (거리순, 30개 페이지네이션)"""
        places = await self.place_repo.find_nearby(lat, lng, cursor=cursor, max_distance=max_distance)
        return self._to_list_dto(places)

    # ──────────────────── 키워드 검색 + 거리순 ────────────────────

    async def search_nearby_places(
        self,
        lat: float,
        lng: float,
        keyword: str,
        cursor: Optional[str] = None,
        max_distance: Optional[float] = None,
    ) -> PlaceListData:
        """키워드 검색 + 거리순 정렬 (display_name, category 매칭)"""
        places = await self.place_repo.search_nearby(lat, lng, keyword, cursor=cursor, max_distance=max_distance)
        return self._to_list_dto(places)

    # ──────────────────── 내부 변환 유틸 ────────────────────

    def _to_list_dto(self, places: list[dict]) -> PlaceListData:
        """raw dict 목록 → PlaceListData 변환 + 다음 커서 생성"""
        place_dtos = [self._to_dto(p) for p in places]

        next_cursor = None
        if len(places) == PAGE_SIZE:
            last = places[-1]
            next_cursor = PlaceRepository.build_cursor(last["distance"], last["place_id"])

        return PlaceListData(places=place_dtos, next_cursor=next_cursor)

    @staticmethod
    def _to_dto(raw: dict) -> PlaceData:
        """MongoDB raw dict → PlaceData DTO 변환"""

        # GeoJSON [lng, lat] → API 친화적 {lat, lng}
        coords = raw.get("location", {}).get("coordinates", [0.0, 0.0])
        location = PlaceLocationData(lat=coords[1], lng=coords[0])

        # price_range 변환
        pr = raw.get("price_range")
        price_range = PlacePriceRangeData(min=pr.get("min"), max=pr.get("max")) if pr else None

        # reviews 변환
        reviews = [
            PlaceReviewData(
                author=r.get("author", ""),
                rating=r.get("rating"),
                relative_time=r.get("relative_time"),
                text=r.get("text"),
            )
            for r in (raw.get("reviews") or [])
        ]

        return PlaceData(
            place_id=raw["place_id"],
            display_name=raw["display_name"],
            category=raw["category"],
            types=raw.get("types", []),
            address=raw["address"],
            short_address=raw.get("short_address"),
            location=location,
            rating=raw.get("rating"),
            rating_count=raw.get("rating_count"),
            price_level=raw.get("price_level"),
            price_range=price_range,
            editorial_summary=raw.get("editorial_summary"),
            generative_summary=raw.get("generative_summary"),
            review_summary=raw.get("review_summary"),
            phone=raw.get("phone"),
            phone_international=raw.get("phone_international"),
            website=raw.get("website"),
            google_maps_url=raw.get("google_maps_url"),
            google_map_review_link=raw.get("google_map_review_link"),
            opening_hours=raw.get("opening_hours"),
            services=raw.get("services"),
            payment=raw.get("payment"),
            accessibility=raw.get("accessibility"),
            parking=raw.get("parking"),
            reviews=reviews,
            distance=raw.get("distance", 0.0),
        )
