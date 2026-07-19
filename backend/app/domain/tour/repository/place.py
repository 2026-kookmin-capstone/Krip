import math
import re
from typing import Literal, Optional

from app.core.instrumentation import measure_mongo_op
from app.domain.tour.model.place import Place


# 장소 조회 개수
PAGE_SIZE = 30


# 식당(types에 'restaurant' 포함)에 한해 음식 옵션을 강제한다.
# 식당이 아닌 장소(공원/박물관 등)는 영향을 받지 않는다.
# 코드는 ``app.core.ai.tour_planner.v2.data_state.FoodPreference``와 동일.
FOOD_FILTER_TYPES: dict[str, list[str]] = {
    "halal": ["halal_restaurant"],
    "vegetarian": ["vegan_restaurant", "vegetarian_restaurant"],
}


def _build_food_filter_query(food_filter: Optional[str]) -> Optional[dict]:
    """음식 필터를 MongoDB 쿼리로 변환.

    - halal: 식당이 아니면 통과 OR types에 halal_restaurant
    - vegetarian: 식당이 아니면 통과 OR types에 vegan_restaurant/vegetarian_restaurant
    - None / any: 필터 미적용
    """
    if not food_filter or food_filter == "any":
        return None
    allowed = FOOD_FILTER_TYPES.get(food_filter)
    if not allowed:
        return None
    return {
        "$or": [
            {"types": {"$nin": ["restaurant"]}},
            {"types": {"$in": allowed}},
        ]
    }


class PlaceRepository:
    """장소 조회 레포지토리 (MongoDB)

    - 모든 조회는 위도/경도 기반 거리순 정렬
    - 커서 기반 페이지네이션 (cursor 형식: "거리:place_id")
    """

    @measure_mongo_op("aggregate", "place")
    async def find_nearby(
        self,
        lat: float,
        lng: float,
        cursor: Optional[str] = None,
        max_distance: Optional[float] = None,
        food_filter: Optional[Literal["halal", "vegetarian", "any"]] = None,
        limit: int = PAGE_SIZE,
    ) -> list[dict]:
        """현재 위치 기준 가까운 장소 조회 (거리순)

        Args:
            max_distance: 최대 검색 반경 (미터 단위, 미지정 시 제한 없음)
            food_filter: 식당에 한해 적용되는 음식 옵션 (halal/vegetarian/any)
            limit: 반환 개수. default는 PAGE_SIZE(=30, 사용자 화면 페이지네이션용).
                planner가 카테고리 그룹별 cap을 채우기 위해 후보를 모을 때는 더 큰 값을 넘긴다.
        """
        return await self._aggregate_nearby(
            lat, lng,
            cursor=cursor,
            max_distance=max_distance,
            food_filter=food_filter,
            limit=limit,
        )

    @measure_mongo_op("aggregate", "place")
    async def search_nearby(
        self,
        lat: float,
        lng: float,
        keyword: str,
        cursor: Optional[str] = None,
        max_distance: Optional[float] = None,
        limit: int = PAGE_SIZE,
    ) -> list[dict]:
        """키워드 검색 + 거리순 정렬 (display_name, category 매칭)

        Args:
            max_distance: 최대 검색 반경 (미터 단위, 미지정 시 제한 없음)
        """
        escaped = re.escape(keyword)
        query = {
            "$or": [
                {"display_name": {"$regex": escaped, "$options": "i"}},
                {"category": {"$regex": escaped, "$options": "i"}},
            ]
        }
        return await self._aggregate_nearby(
            lat, lng, query=query, cursor=cursor, max_distance=max_distance, limit=limit,
        )

    @measure_mongo_op("find_one", "place")
    async def find_by_place_id(self, place_id: str) -> Optional[dict]:
        """place_id로 장소 단건 조회"""
        collection = Place.get_motor_collection()
        return await collection.find_one({"place_id": place_id})

    @measure_mongo_op("find", "place")
    async def find_by_place_ids(self, place_ids: list[str]) -> list[dict]:
        """place_id 목록으로 장소 배치 조회"""
        if not place_ids:
            return []
        collection = Place.get_motor_collection()
        cursor = collection.find({"place_id": {"$in": place_ids}})
        return await cursor.to_list(length=len(place_ids))

    async def _aggregate_nearby(
        self,
        lat: float,
        lng: float,
        query: Optional[dict] = None,
        cursor: Optional[str] = None,
        max_distance: Optional[float] = None,
        food_filter: Optional[Literal["halal", "vegetarian", "any"]] = None,
        limit: int = PAGE_SIZE,
    ) -> list[dict]:
        """$geoNear 거리와 place_id의 total order로 cursor page를 조회한다."""
        collection = Place.get_motor_collection()

        cursor_distance = None
        cursor_place_id = None
        if cursor:
            cursor_distance, cursor_place_id = self._parse_cursor(cursor)

        geo_near: dict = {
            "$geoNear": {
                "near": {"type": "Point", "coordinates": [lng, lat]},
                "distanceField": "distance",
                "spherical": True,
            }
        }

        food_query = _build_food_filter_query(food_filter)
        if query and food_query:
            geo_near["$geoNear"]["query"] = {"$and": [query, food_query]}
        elif query:
            geo_near["$geoNear"]["query"] = query
        elif food_query:
            geo_near["$geoNear"]["query"] = food_query

        if max_distance is not None:
            geo_near["$geoNear"]["maxDistance"] = max_distance

        # 동일 거리 문서를 cursor의 place_id로 거르기 위해 작은 거리 여유를 둔다.
        if cursor_distance is not None:
            geo_near["$geoNear"]["minDistance"] = max(0, cursor_distance - 1e-2)

        pipeline: list[dict] = [geo_near]

        pipeline.append({"$sort": {"distance": 1, "place_id": 1}})

        if cursor_distance is not None and cursor_place_id is not None:
            pipeline.append({
                "$match": {
                    "$or": [
                        {"distance": {"$gt": cursor_distance}},
                        {
                            "distance": cursor_distance,
                            "place_id": {"$gt": cursor_place_id},
                        },
                    ]
                }
            })

        pipeline.append({"$limit": limit})

        return await collection.aggregate(pipeline).to_list(limit)

    @staticmethod
    def _parse_cursor(cursor: str) -> tuple[float, str]:
        """커서 문자열 파싱 → (distance, place_id)

        형식은 "거리:place_id". 다음 케이스는 모두 도메인 표준 ValueError 로 거부해
        라우터가 400(일반 메시지)으로 매핑하도록 한다 (raw Python 에러 노출 방지):
            - 구분자(:) 누락 등 구조 불량
            - place_id 누락(빈 문자열)
            - distance 가 숫자가 아니거나 nan/inf (비유한). nan 은 $match 로 조용히
              빈 페이지를, inf 는 $geoNear minDistance=Infinity 로 정의되지 않은 동작을 유발.
        """
        parts = cursor.split(":", 1)
        if len(parts) != 2:
            raise ValueError("유효하지 않은 커서입니다.")
        distance_str, place_id = parts
        if not place_id:
            raise ValueError("유효하지 않은 커서입니다.")
        try:
            distance = float(distance_str)
        except ValueError:
            raise ValueError("유효하지 않은 커서입니다.") from None
        if not math.isfinite(distance):
            raise ValueError("유효하지 않은 커서입니다.")
        return distance, place_id

    @staticmethod
    def build_cursor(distance: float, place_id: str) -> str:
        """다음 페이지 커서 생성 (service에서 호출)"""
        return f"{distance}:{place_id}"
