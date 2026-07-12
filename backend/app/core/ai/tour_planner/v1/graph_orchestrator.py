import asyncio
import time
from functools import lru_cache
from typing import Any, Dict, List

from langgraph.graph import END, START, StateGraph

from app.core.ai.tour_planner.v1.chain_builder import (
    TourPlanResult,
    get_tour_planner_chain_builder,
)
from app.core.ai.tour_planner.v1.graph_state import TourPlannerGraphState
from app.core.logger import get_logger
from app.domain.tour.repository.place import PlaceRepository


logger = get_logger("Tour Planner Graph Orchestrator")

# MongoDB 검색 반경 (미터)
SEARCH_RADIUS_METERS = 1500

# 일자당 최대 장소 수 (프롬프트 토큰 제한 고려)
MAX_PLACES_PER_DAY = 30


class TourPlannerGraphOrchestrator:
    """Tour Planner LangGraph 오케스트레이터"""

    def __init__(self):
        self._chain_manager = get_tour_planner_chain_builder()
        self._place_repo = PlaceRepository()
        self._graph: Any = None

    async def initialize(self) -> None:
        """그래프와 관련 컴포넌트를 초기화합니다."""
        self._chain_manager.build_all_chains()
        self._build_graph()

    async def _recommend_destinations(self, state: TourPlannerGraphState) -> Dict[str, Any]:
        """1차: 사용자 입력 기반 권역/좌표 추천"""
        chain = self._chain_manager.get_chain('recommend_destinations')

        result = await chain.ainvoke({
            "travel_days": state["travel_days"],
            "travel_style": state["travel_style"],
            "budget": state["budget"],
            "companion_type": state["companion_type"],
            "schedule_density": state["schedule_density"],
        })

        logger.info(
            "1차 권역 추천 완료: {:d}일 / {}",
            state["travel_days"],
            [r.cluster_name for r in result.recommendations],
        )

        return {"recommendations": result}

    async def _search_places(self, state: TourPlannerGraphState) -> Dict[str, Any]:
        recommendations = state["recommendations"]
        places_data: List[dict] = []

        for day_rec in recommendations.recommendations:
            search_tasks = [
                self._place_repo.find_nearby(
                    lat=place.latitude,
                    lng=place.longitude,
                    max_distance=SEARCH_RADIUS_METERS,
                )
                for place in day_rec.places
            ]
            search_results = await asyncio.gather(*search_tasks)

            seen_ids: set[str] = set()
            merged: List[dict] = []
            for places in search_results:
                for place in places:
                    pid = place["place_id"]
                    if pid not in seen_ids:
                        seen_ids.add(pid)
                        merged.append(place)

            merged.sort(key=lambda p: (p.get("rating") or 0, p.get("rating_count") or 0), reverse=True)
            merged = merged[:MAX_PLACES_PER_DAY]

            places_data.append({
                "day": day_rec.day,
                "cluster_name": day_rec.cluster_name,
                "places": merged,
            })

            logger.info(
                "MongoDB 검색 완료: Day {:d} ({}) → {:d}개 장소",
                day_rec.day, day_rec.cluster_name, len(merged),
            )

        return {"places_data": places_data}

    async def _build_tour_plan(self, state: TourPlannerGraphState) -> Dict[str, Any]:
        chain = self._chain_manager.get_chain('build_tour_plan')

        result = await chain.ainvoke({
            "travel_days": state["travel_days"],
            "travel_style": state["travel_style"],
            "budget": state["budget"],
            "companion_type": state["companion_type"],
            "schedule_density": state["schedule_density"],
            "recommendations": self._format_recommendations(state["recommendations"]),
            "places_data": self._format_places_data(state["places_data"]),
        })

        logger.info(
            "최종 여행 플랜 생성 완료: {:d}일 / 총 {:d}개 장소",
            len(result.tour_plan),
            sum(len(day.places) for day in result.tour_plan),
        )

        return {"tour_plan": result}

    def _build_graph(self) -> None:
        graph_builder = StateGraph(TourPlannerGraphState)

        graph_builder.add_node("RecommendDestinations", self._recommend_destinations)
        graph_builder.add_node("SearchPlaces", self._search_places)
        graph_builder.add_node("BuildTourPlan", self._build_tour_plan)

        graph_builder.add_edge(START, "RecommendDestinations")
        graph_builder.add_edge("RecommendDestinations", "SearchPlaces")
        graph_builder.add_edge("SearchPlaces", "BuildTourPlan")
        graph_builder.add_edge("BuildTourPlan", END)

        self._graph = graph_builder.compile()

    def get_graph(self) -> Any:
        return self._graph

    async def ainvoke(
        self,
        travel_days: int,
        travel_style: str,
        budget: str,
        companion_type: str,
        schedule_density: str,
    ) -> TourPlanResult:
        input_data: TourPlannerGraphState = {
            "travel_days": travel_days,
            "travel_style": travel_style,
            "budget": budget,
            "companion_type": companion_type,
            "schedule_density": schedule_density,
            "recommendations": None,
            "places_data": [],
            "tour_plan": None,
        }

        start_time = time.perf_counter()

        response = await self._graph.ainvoke(input_data)

        elapsed = time.perf_counter() - start_time
        logger.info("Tour Planner 완료: {:.2f}초", elapsed)

        return response["tour_plan"]

    @staticmethod
    def _format_recommendations(recommendations) -> str:
        lines: List[str] = []

        for day_rec in recommendations.recommendations:
            lines.append(f"### Day {day_rec.day} - {day_rec.cluster_name}")
            for place in day_rec.places:
                lines.append(f"- {place.name} (위도: {place.latitude}, 경도: {place.longitude}) → {place.reason}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_places_data(places_data: List[dict]) -> str:
        lines: List[str] = []

        for day_data in places_data:
            lines.append(f"### Day {day_data['day']} - {day_data['cluster_name']} ({len(day_data['places'])}개 장소)")
            lines.append("")

            for i, place in enumerate(day_data["places"], 1):
                coords = place.get("location", {}).get("coordinates", [0, 0])
                lng, lat = coords[0], coords[1]

                # 요약: editorial > generative > review 우선순위
                summary = (
                    place.get("editorial_summary")
                    or place.get("generative_summary")
                    or place.get("review_summary")
                    or ""
                )

                lines.append(f"[{i}] {place['display_name']} ({place['category']})")
                lines.append(f"  - place_id: {place['place_id']}")
                lines.append(f"  - 주소: {place.get('short_address') or place['address']}")
                lines.append(f"  - 좌표: ({lat}, {lng})")

                if place.get("rating"):
                    rating_str = f"  - 별점: {place['rating']}"
                    if place.get("rating_count"):
                        rating_str += f" (리뷰 {place['rating_count']:,}개)"
                    lines.append(rating_str)

                if place.get("price_level"):
                    lines.append(f"  - 가격: {place['price_level']}")

                if summary:
                    lines.append(f"  - 요약: {summary}")

                if place.get("opening_hours"):
                    hours_str = " / ".join(place["opening_hours"][:3])
                    lines.append(f"  - 영업시간: {hours_str}")

                lines.append("")

        return "\n".join(lines)


@lru_cache(maxsize=1)
def get_tour_planner_graph() -> TourPlannerGraphOrchestrator:
    """TourPlannerGraphOrchestrator 싱글톤 인스턴스를 반환합니다."""
    return TourPlannerGraphOrchestrator()
