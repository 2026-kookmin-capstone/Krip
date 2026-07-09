"""투어 플랜 schema(app.domain.tour.schema.tour_plan) 검증 테스트.

플랜 카드 개수 / 여행 일수 상한이 DB insert 단계(int4 overflow·대량 write) 대신
요청 단계 ValidationError(422)로 걸러지는지 회귀 가드. 상한이 없으면 500k 카드 POST 로
RDB/Mongo 팽창 + 공개 공유 엔드포인트 미인증 증폭을 유발.
"""
import pytest
from pydantic import ValidationError

from app.domain.tour.schema.tour_plan import (
    _MAX_PLAN_ITEMS,
    _MAX_TRAVEL_DAYS,
    CreatePlanRequest,
)


def _item(day_number: int = 1):
    return {"day_number": day_number, "place_id": "ChIJExample", "visit_time": "10:00"}


def _payload(**overrides):
    base = {
        "title": "서울 3일 여행",
        "travel_days": 3,
        "items": [_item(1)],
    }
    base.update(overrides)
    return base


@pytest.mark.unit
class TestPlanItemCountLimit:
    def test_at_cap_allowed(self):
        CreatePlanRequest(**_payload(items=[_item(1) for _ in range(_MAX_PLAN_ITEMS)]))

    def test_over_cap_rejected(self):
        with pytest.raises(ValidationError):
            CreatePlanRequest(**_payload(items=[_item(1) for _ in range(_MAX_PLAN_ITEMS + 1)]))

    def test_empty_items_rejected(self):
        with pytest.raises(ValidationError):
            CreatePlanRequest(**_payload(items=[]))


@pytest.mark.unit
class TestTravelDaysLimit:
    def test_at_cap_allowed(self):
        CreatePlanRequest(**_payload(travel_days=_MAX_TRAVEL_DAYS))

    def test_over_cap_rejected(self):
        with pytest.raises(ValidationError):
            CreatePlanRequest(**_payload(travel_days=_MAX_TRAVEL_DAYS + 1))

    def test_zero_rejected(self):
        with pytest.raises(ValidationError):
            CreatePlanRequest(**_payload(travel_days=0))


@pytest.mark.unit
class TestItemDayNumberLimit:
    def test_over_cap_rejected(self):
        with pytest.raises(ValidationError):
            CreatePlanRequest(**_payload(items=[_item(_MAX_TRAVEL_DAYS + 1)]))
