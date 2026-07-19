from typing import List, TypedDict

from app.core.ai.tour_planner.v1.chain_builder import (
    TourPlanResult,
    TourRecommendationResult,
)


class TourPlannerGraphState(TypedDict):
    """Tour Planner LangGraph 상태 정의"""

    travel_days: int
    travel_style: str
    budget: str
    companion_type: str
    schedule_density: str

    recommendations: TourRecommendationResult

    places_data: List[dict]

    tour_plan: TourPlanResult
