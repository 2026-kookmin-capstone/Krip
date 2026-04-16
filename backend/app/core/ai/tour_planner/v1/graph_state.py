from typing import List, TypedDict

from app.core.ai.tour_planner.v1.chain_builder import (
    TourRecommendationResult,
    TourPlanResult,
)


class TourPlannerGraphState(TypedDict):
    """Tour Planner LangGraph 상태 정의"""

    # ── 사용자 입력 ──
    travel_days: int                                    # 여행 일수
    travel_style: str                                   # 여행 스타일 (맛집 탐방, 쇼핑, 문화/역사, 카페/힙플레이스, 자연/공원)
    budget: str                                         # 여행 예산 (저예산, 중간, 고예산)
    companion_type: str                                 # 동행 유형 (혼자, 연인, 친구, 가족)
    schedule_density: str                               # 선호 일정 밀도 (빽빽하게, 보통, 널널하게)

    # ── 1차: 권역 추천 결과 ──
    recommendations: TourRecommendationResult           # 1차 추천 결과 (Pydantic 모델)

    # ── 2차: MongoDB 검색 결과 ──
    places_data: List[dict]                             # 권역별 실제 장소 데이터 (day별 raw dict 리스트)

    # ── 최종 결과 ──
    tour_plan: TourPlanResult                           # 최종 여행 플랜 (Pydantic 모델)
