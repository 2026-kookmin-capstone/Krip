"""Tour Planner v2 데이터 단일 진입점.

- 사용자 입력 / 최종 출력 Pydantic 모델
- LangGraph 상태 TypedDict

서비스가 외국인 한국 여행자 대상이라 모든 사용자 노출 텍스트(LLM 출력 포함)는
영어로 통일한다. Pydantic Field description과 class docstring은
``with_structured_output``을 통해 LLM schema로 전달되므로 영어로 작성한다.
"""

from typing import List, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


class TourPlannerOutputError(Exception):
    """LLM 이 유효한 구조화 출력을 내지 못함 (None / 파싱 실패 / 스키마 위반).

    입력 오류(400)가 아닌 vendor 출력 문제라 서비스가 502 로 매핑한다. raw 출력이
    사용자 응답에 새지 않도록 메시지는 일반화한다.
    """


FoodPreference = Literal["halal", "vegetarian", "any"]

Transport = Literal["public_transport"]

Companion = Literal[
    "solo",
    "couple",
    "spouse",
    "friends_colleagues",
    "family_parents",
    "family_with_kids",
]

TravelStyle = Literal[
    "activity",
    "famous_attractions",
    "healing",
    "culture_history",
    "shopping",
    "food_tour",
    "photo_aesthetic",
    "festival_event",
]

ScheduleDensity = Literal["relaxed", "packed"]


class TourDayInput(BaseModel):
    """Per-day user input."""

    departure_cluster: str = Field(description="Departure cluster (English standard name).")
    arrival_cluster: str = Field(description="Arrival cluster (English standard name).")
    additional_place_id: Optional[str] = Field(None, description="place_id of a required must-visit place. None if not specified.")
    transport: Transport = Field(description="Transportation mode.")
    start_time: str = Field(description="Start time in HH:MM (24h).")
    end_time: str = Field(description="End time in HH:MM (24h).")
    companion: Companion = Field(description="Companion type.")
    budget_per_person_krw: int = Field(description="Per-person budget in KRW.")
    styles: List[TravelStyle] = Field(description="Travel styles (multi-select).")
    schedule_density: ScheduleDensity = Field(description="Schedule density.")


class TourPlannerInput(BaseModel):
    """Full planner input."""

    travel_days: int = Field(ge=1, le=3, description="Number of travel days (1-3).")
    food_preference: FoodPreference = Field(description="Food preference option.")
    days: List[TourDayInput] = Field(description="Per-day inputs. len(days) MUST equal travel_days.")


class TourPlanLocation(BaseModel):
    """Coordinate."""

    lat: float = Field(description="Latitude.")
    lng: float = Field(description="Longitude.")


class TourTimelineSlot(BaseModel):
    """Timeline slot."""

    time: str = Field(description="Time in HH:MM (24h).")
    place_id: str = Field(description="place_id at this slot. MUST reference an existing place in `places` (or the Required Additional Place). Transit between venues is described in the `movements` array, not as a timeline slot.")
    title: str = Field(description="Slot description in English. Format: 'Place Name → Activity' (e.g. 'Bukchon Hanok Village → Stroll the alleys').")


class TourPlaceDetail(BaseModel):
    """Place detail."""

    place_id: str = Field(description="Google Places unique ID.")
    display_name: str = Field(description="Place name.")
    category: str = Field(description="Place category.")
    address: str = Field(description="Address.")
    location: TourPlanLocation = Field(description="Coordinate.")
    rating: Optional[float] = Field(None, description="Average rating.")
    reason: str = Field(description="Reason and highlights in English (2-3 sentences).")
    estimated_cost_krw: int = Field(ge=0, description="Estimated per-person spend in KRW. Use 0 for free places (parks, public streets, free landmarks).")
    stay_minutes: int = Field(gt=0, description="Recommended stay in minutes. Typical: meals 60-90, cafes 60, attractions 60-120, shopping 60, nightlife 90.")
    is_additional: bool = Field(False, description="True if this is the user-required must-visit place.")
    photos: List[str] = Field(default_factory=list, description="Photo URLs. DO NOT POPULATE — leave as []. Server overwrites this from the database after your response.")


class TourMovementHop(BaseModel):
    """Movement hop between two places."""

    from_place: str = Field(description="Origin place name.")
    to_place: str = Field(description="Destination place name.")
    method: str = Field(description="Movement description in English (e.g. 'Subway Line 2 → 5 min walk').")


class TourBudgetItem(BaseModel):
    """Budget breakdown item."""

    label: str = Field(description="Item label in English (e.g. 'Lunch', 'Cafe', 'Admission').")
    amount_krw: int = Field(description="Amount in KRW.")


class TourDayPlan(BaseModel):
    """Per-day final plan."""

    day: int = Field(description="Day number (1-indexed).")
    timeline: List[TourTimelineSlot] = Field(description="Time-based itinerary, ordered by time.")
    places: List[TourPlaceDetail] = Field(description="Detailed list of selected places.")
    movements: List[TourMovementHop] = Field(description="Movement hops between adjacent places.")
    budget_breakdown: List[TourBudgetItem] = Field(description="Budget items. Sum MUST NOT exceed budget_per_person_krw.")
    budget_total_krw: int = Field(description="Total budget in KRW (sum of budget_breakdown).")
    summary: str = Field(description="Closing summary in English (2-3 sentences).")


class TourPlanResult(BaseModel):
    """Final tour plan covering all days."""

    tour_plan: List[TourDayPlan] = Field(description="One plan per day.")


class TourPlannerGraphState(TypedDict):
    """Tour Planner v2 LangGraph 상태"""

    travel_days: int
    food_preference: FoodPreference
    days_input: List[TourDayInput]

    fixed_places: List[Optional[dict]]

    candidate_places: List[List[dict]]

    tour_plan: TourPlanResult
