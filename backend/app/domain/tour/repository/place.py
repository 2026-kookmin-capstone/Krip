from typing import Optional
import re

from app.domain.tour.model.place import Place


# 장소 조회 개수
PAGE_SIZE = 30


class PlaceRepository:
    """장소 조회 레포지토리 (MongoDB)

    - 모든 조회는 위도/경도 기반 거리순 정렬
    - 커서 기반 페이지네이션 (cursor 형식: "거리:place_id")
    """

    # ──────────────────── Read (거리순 조회) ────────────────────

    async def find_nearby(
        self,
        lat: float,
        lng: float,
        cursor: Optional[str] = None,
        max_distance: Optional[float] = None,
    ) -> list[dict]:
        """현재 위치 기준 가까운 장소 30개 조회 (거리순)

        Args:
            max_distance: 최대 검색 반경 (미터 단위, 미지정 시 제한 없음)
        """
        return await self._aggregate_nearby(lat, lng, cursor=cursor, max_distance=max_distance)

    # ──────────────────── Read (키워드 검색 + 거리순) ────────────────────

    async def search_nearby(
        self,
        lat: float,
        lng: float,
        keyword: str,
        cursor: Optional[str] = None,
        max_distance: Optional[float] = None,
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
        return await self._aggregate_nearby(lat, lng, query=query, cursor=cursor, max_distance=max_distance)

    # ──────────────────── 내부 유틸 ────────────────────

    async def _aggregate_nearby(
        self,
        lat: float,
        lng: float,
        query: Optional[dict] = None,
        cursor: Optional[str] = None,
        max_distance: Optional[float] = None,
    ) -> list[dict]:
        """$geoNear 기반 거리순 조회 공통 로직

        파이프라인 구조:
            1. $geoNear  — 기준점으로부터 거리 계산 + 거리순 정렬
            2. $sort     — 동일 거리 내 place_id 오름차순 (정렬 안정성 보장)
            3. $match    — 커서 이후 데이터만 필터링
            4. $limit    — PAGE_SIZE만큼 제한
        """
        collection = Place.get_motor_collection()

        # 커서 파싱 (있을 경우)
        cursor_distance = None
        cursor_place_id = None
        if cursor:
            cursor_distance, cursor_place_id = self._parse_cursor(cursor)

        # ── $geoNear 스테이지 ──
        geo_near: dict = {
            "$geoNear": {
                "near": {"type": "Point", "coordinates": [lng, lat]},
                "distanceField": "distance",
                "spherical": True,
            }
        }

        if query:
            geo_near["$geoNear"]["query"] = query

        if max_distance is not None:
            geo_near["$geoNear"]["maxDistance"] = max_distance

        # minDistance: 동일 거리 문서가 잘리지 않도록 epsilon 보정
        if cursor_distance is not None:
            geo_near["$geoNear"]["minDistance"] = max(0, cursor_distance - 1e-2)

        pipeline: list[dict] = [geo_near]

        # ── $sort 스테이지 (동일 거리 내 정렬 안정성 보장) ──
        pipeline.append({"$sort": {"distance": 1, "place_id": 1}})

        # ── $match 스테이지 (커서 이후 필터링) ──
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

        # ── $limit 스테이지 ──
        pipeline.append({"$limit": PAGE_SIZE})

        return await collection.aggregate(pipeline).to_list(PAGE_SIZE)


    @staticmethod
    def _parse_cursor(cursor: str) -> tuple[float, str]:
        """커서 문자열 파싱 → (distance, place_id)"""
        distance_str, place_id = cursor.split(":", 1)
        return float(distance_str), place_id


    @staticmethod
    def build_cursor(distance: float, place_id: str) -> str:
        """다음 페이지 커서 생성 (service에서 호출)"""
        return f"{distance}:{place_id}"
