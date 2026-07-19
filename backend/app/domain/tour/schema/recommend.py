import re
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from app.core.ai.tour_planner.v2.data_state import (
    Companion,
    FoodPreference,
    ScheduleDensity,
    Transport,
    TravelStyle,
)
from app.core.ai.tour_planner.v2.prompt_manager import CLUSTER_COORDINATES


_TIME_PATTERN = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _to_minutes(hhmm: str) -> int:
    """HH:MM → 분 단위 정수. 형식이 깨지면 -1."""
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


class TourDayRequest(BaseModel):
    """Per-day tour recommendation request."""

    departure_cluster: str = Field(..., description="Departure cluster name (must be a key of CLUSTER_COORDINATES).")
    arrival_cluster: str = Field(..., description="Arrival cluster name.")
    additional_place_id: Optional[str] = Field(None, description="place_id of a required must-visit place. Up to 1.")
    transport: Transport = Field(..., description="Transportation mode.")
    start_time: str = Field(..., description="Start time in HH:MM (24h).")
    end_time: str = Field(..., description="End time in HH:MM (24h).")
    companion: Companion = Field(..., description="Companion type.")
    budget_per_person_krw: int = Field(..., ge=0, description="Per-person budget in KRW.")
    styles: List[TravelStyle] = Field(..., min_length=1, description="Travel styles (multi-select, at least one).")
    schedule_density: ScheduleDensity = Field(..., description="Schedule density.")

    @field_validator("departure_cluster", "arrival_cluster")
    @classmethod
    def _validate_cluster(cls, v: str) -> str:
        if v not in CLUSTER_COORDINATES:
            raise ValueError(f"Unknown cluster name: {v}")
        return v

    @field_validator("start_time", "end_time")
    @classmethod
    def _validate_time_format(cls, v: str) -> str:
        if not _TIME_PATTERN.match(v):
            raise ValueError(f"Invalid time format (expected HH:MM 24h): {v}")
        return v

    @model_validator(mode="after")
    def _validate_time_range(self) -> "TourDayRequest":
        if _to_minutes(self.start_time) >= _to_minutes(self.end_time):
            raise ValueError(
                f"start_time ({self.start_time}) must be earlier than end_time ({self.end_time})"
            )
        return self


class TourRecommendRequest(BaseModel):
    """Tour recommendation request (full)."""

    travel_days: int = Field(..., ge=1, le=3, description="Number of travel days (1-3).")
    food_preference: FoodPreference = Field(..., description="Food preference (halal / vegetarian / any).")
    days: List[TourDayRequest] = Field(..., description="Per-day inputs. len(days) MUST equal travel_days.")

    @model_validator(mode="after")
    def _validate_days_length(self) -> "TourRecommendRequest":
        if len(self.days) != self.travel_days:
            raise ValueError(
                f"len(days)={len(self.days)} does not match travel_days={self.travel_days}"
            )
        return self


class TourPlaceLocationResponse(BaseModel):
    """Coordinate."""

    lat: float = Field(..., description="Latitude.")
    lng: float = Field(..., description="Longitude.")


class TourTimelineSlotResponse(BaseModel):
    """Timeline slot in the day plan."""

    time: str = Field(..., description="Time in HH:MM (24h).")
    place_id: str = Field(..., description="place_id at this slot (always present — every slot is a real venue from `places`).")
    title: str = Field(..., description="Slot description (English).")


class TourPlaceDetailResponse(BaseModel):
    """Place detail in the day plan."""

    place_id: str = Field(..., description="Google Places unique ID.")
    display_name: str = Field(..., description="Place name.")
    category: str = Field(..., description="Place category.")
    address: str = Field(..., description="Address.")
    location: TourPlaceLocationResponse = Field(..., description="Coordinate.")
    rating: Optional[float] = Field(None, description="Average rating.")
    reason: str = Field(..., description="Reason and highlights (English).")
    estimated_cost_krw: int = Field(..., ge=0, description="Estimated per-person spend in KRW. 0 does NOT necessarily mean free — it may also indicate a missing/unknown estimate. Do not render as 'Free' without independent verification.")
    stay_minutes: int = Field(..., gt=0, description="Recommended stay in minutes (positive).")
    photos: List[str] = Field(default_factory=list, description="Photo URL list (empty if no image available).")


class TourMovementHopResponse(BaseModel):
    """Movement hop between two places."""

    from_place: str = Field(..., description="Origin place name.")
    to_place: str = Field(..., description="Destination place name.")
    method: str = Field(..., description="Movement description (English).")


class TourBudgetItemResponse(BaseModel):
    """Budget breakdown item."""

    label: str = Field(..., description="Item label (English).")
    amount_krw: int = Field(..., description="Amount in KRW.")


class TourDayResponse(BaseModel):
    """Per-day final plan."""

    day: int = Field(..., description="Day number (1-indexed).")
    timeline: List[TourTimelineSlotResponse] = Field(..., description="Time-based itinerary, ordered by time.")
    places: List[TourPlaceDetailResponse] = Field(..., description="Detailed list of selected places.")
    movements: List[TourMovementHopResponse] = Field(..., description="Movement hops between adjacent places.")
    budget_breakdown: List[TourBudgetItemResponse] = Field(..., description="Budget items.")
    budget_total_krw: int = Field(..., description="Total budget in KRW.")
    summary: str = Field(..., description="Closing summary (English).")


class TourRecommendResponse(BaseModel):
    """Tour recommendation response (full)."""

    tour_plan: List[TourDayResponse] = Field(..., description="One plan per day.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "tour_plan": [
                    {
                        "day": 1,
                        "timeline": [
                            {"time": "10:00", "place_id": "ChIJExampleHongdaeCafe", "title": "Thanks Nature Cafe → Brunch & Coffee"},
                            {"time": "12:00", "place_id": "ChIJExampleYeonnamPark", "title": "Gyeongui Line Forest Park → Stroll & Photo"},
                            {"time": "13:30", "place_id": "ChIJ0X7IQw2jfDURa8XanOsn0cw", "title": "Cherry Garden Restaurant → Halal Korean Lunch"},
                            {"time": "15:00", "place_id": "ChIJExampleBukchon", "title": "Bukchon Hanok Village → Traditional Architecture Walk"},
                            {"time": "17:00", "place_id": "ChIJExampleInsadong", "title": "Insadong Street → Souvenir Shopping"},
                            {"time": "18:30", "place_id": "ChIJExampleMyeongdong", "title": "Myeongdong → Street Food Dinner"},
                            {"time": "20:30", "place_id": "ChIJExampleNSeoulTower", "title": "N Seoul Tower → Night View"},
                        ],
                        "places": [
                            {
                                "place_id": "ChIJExampleHongdaeCafe",
                                "display_name": "Thanks Nature Cafe",
                                "category": "Cafe",
                                "address": "Mapo-gu, Seoul",
                                "location": {"lat": 37.5546, "lng": 126.9237},
                                "rating": 4.4,
                                "reason": "Foreigner-friendly Hongdae cafe famous for its resident sheep and brunch menu. A relaxed kickoff for a couple's morning.",
                                "estimated_cost_krw": 18000,
                                "stay_minutes": 90,
                            },
                            {
                                "place_id": "ChIJExampleYeonnamPark",
                                "display_name": "Gyeongui Line Forest Park",
                                "category": "Park",
                                "address": "Mapo-gu, Seoul",
                                "location": {"lat": 37.5615, "lng": 126.9251},
                                "rating": 4.5,
                                "reason": "A linear park threading through Yeonnam-dong, ideal for a slow walk between cafes and small shops with plenty of photo spots.",
                                "estimated_cost_krw": 0,
                                "stay_minutes": 60,
                            },
                            {
                                "place_id": "ChIJ0X7IQw2jfDURa8XanOsn0cw",
                                "display_name": "Cherry Garden Restaurant (Halal)",
                                "category": "Korean restaurant",
                                "address": "Jongno-gu, Seoul",
                                "location": {"lat": 37.5723, "lng": 127.0140},
                                "rating": 5.0,
                                "reason": "Halal-certified Korean restaurant near Jongno, offering traditional dishes that comply with halal requirements — a comfortable lunch choice for Muslim travelers.",
                                "estimated_cost_krw": 18000,
                                "stay_minutes": 75,
                            },
                            {
                                "place_id": "ChIJExampleBukchon",
                                "display_name": "Bukchon Hanok Village",
                                "category": "Cultural landmark",
                                "address": "Jongno-gu, Seoul",
                                "location": {"lat": 37.5825, "lng": 126.9836},
                                "rating": 4.3,
                                "reason": "Preserved hanok neighborhood with sweeping rooftop views over Seoul. The user-designated must-visit on this trip.",
                                "estimated_cost_krw": 0,
                                "stay_minutes": 90,
                            },
                            {
                                "place_id": "ChIJExampleInsadong",
                                "display_name": "Insadong Street",
                                "category": "Shopping street",
                                "address": "Jongno-gu, Seoul",
                                "location": {"lat": 37.5740, "lng": 126.9853},
                                "rating": 4.4,
                                "reason": "Traditional craft and souvenir street within walking distance of Bukchon — calligraphy, ceramics, and tea houses.",
                                "estimated_cost_krw": 7000,
                                "stay_minutes": 60,
                            },
                            {
                                "place_id": "ChIJExampleMyeongdong",
                                "display_name": "Myeongdong",
                                "category": "Shopping & food street",
                                "address": "Jung-gu, Seoul",
                                "location": {"lat": 37.5636, "lng": 126.9826},
                                "rating": 4.4,
                                "reason": "Seoul's iconic shopping district with halal-friendly street food and cosmetic shops, lively in the evening for couples.",
                                "estimated_cost_krw": 22000,
                                "stay_minutes": 90,
                            },
                            {
                                "place_id": "ChIJExampleNSeoulTower",
                                "display_name": "N Seoul Tower",
                                "category": "Observation deck",
                                "address": "Yongsan-gu, Seoul",
                                "location": {"lat": 37.5512, "lng": 126.9882},
                                "rating": 4.5,
                                "reason": "Closing the day with Seoul's most iconic night view from Namsan, a short cable car ride from Myeongdong.",
                                "estimated_cost_krw": 5000,
                                "stay_minutes": 60,
                            },
                        ],
                        "movements": [
                            {"from_place": "Thanks Nature Cafe", "to_place": "Gyeongui Line Forest Park", "method": "5 min walk"},
                            {"from_place": "Gyeongui Line Forest Park", "to_place": "Cherry Garden Restaurant (Halal)", "method": "Subway Line 2 → Line 1 → 7 min walk"},
                            {"from_place": "Cherry Garden Restaurant (Halal)", "to_place": "Bukchon Hanok Village", "method": "12 min walk"},
                            {"from_place": "Bukchon Hanok Village", "to_place": "Insadong Street", "method": "10 min walk"},
                            {"from_place": "Insadong Street", "to_place": "Myeongdong", "method": "Subway Line 3 → Line 4 (Euljiro 3-ga transfer)"},
                            {"from_place": "Myeongdong", "to_place": "N Seoul Tower", "method": "Namsan cable car → 3 min walk"},
                        ],
                        "budget_breakdown": [
                            {"label": "Brunch & Cafe", "amount_krw": 18000},
                            {"label": "Halal Lunch", "amount_krw": 18000},
                            {"label": "Dinner & Street Food", "amount_krw": 22000},
                            {"label": "Snacks & Admission", "amount_krw": 12000},
                        ],
                        "budget_total_krw": 70000,
                        "summary": "A natural arc through Seoul's three signature axes — Hongdae's trendy youth scene, Bukchon's preserved tradition, and Myeongdong's commercial buzz — closing with the N Seoul Tower night view. Lunch is anchored by halal-certified Cherry Garden so the day stays comfortable for Muslim travelers.",
                    }
                ]
            }
        }
    }
