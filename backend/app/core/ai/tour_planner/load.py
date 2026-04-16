from app.core.ai.tour_planner.v1.graph_orchestrator import (
    TourPlannerGraphOrchestrator,
    get_tour_planner_graph,
)
from app.core.ai.tour_planner.v1.chain_builder import TourPlanResult


class TourPlanner:
    """Tour Planner — 사용자 맞춤 서울 여행 코스를 생성합니다."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance


    async def load(self) -> None:
        """서버 시작 시 한 번 호출된다."""
        if self._initialized:
            return
        self._orchestrator = get_tour_planner_graph()
        await self._orchestrator.initialize()
        self._initialized = True


    async def invoke(
        self,
        travel_days: int,
        travel_style: str,
        budget: str,
        companion_type: str,
        schedule_density: str,
    ) -> TourPlanResult:
        """
        추론 요청의 단일 진입점.

        Args:
            travel_days: 여행 일수
            travel_style: 여행 스타일 (맛집 탐방, 쇼핑, 문화/역사, 카페/힙플레이스, 자연/공원)
            budget: 여행 예산 (저예산, 중간, 고예산)
            companion_type: 동행 유형 (혼자, 연인, 친구, 가족)
            schedule_density: 선호 일정 밀도 (빽빽하게, 보통, 널널하게)

        Returns:
            TourPlanResult:
                tour_plan: list[TourPlanDay]
                    - day: int
                    - cluster_name: str
                    - places: list[TourPlanPlace]
                        - place_id: str
                        - display_name: str
                        - category: str
                        - address: str
                        - location: TourPlanLocation (lat, lng)
                        - rating: float | None
                        - description: str
                        - tip: str
        """
        if not self._initialized:
            raise RuntimeError("모델이 로드되지 않았습니다.")

        return await self._orchestrator.ainvoke(
            travel_days=travel_days,
            travel_style=travel_style,
            budget=budget,
            companion_type=companion_type,
            schedule_density=schedule_density,
        )
