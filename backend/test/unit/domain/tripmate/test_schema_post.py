"""여행메이트 게시글 schema(app.domain.tripmate.schema.tripmate_post) 검증 테스트.

_validate_post_ranges 교차 검증(나이 하한≤상한 / 여행 시작≤종료)이 DB CheckConstraint(500)
대신 요청 단계 ValidationError(422)로 걸러지는지 회귀 가드. Create/Update 양쪽 동일 적용.
"""
from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.tripmate.schema.tripmate_post import CreatePostRequest, UpdatePostRequest


def _payload(**overrides):
    base = {
        "title": "제주도 같이 가실 분",
        "content": "7월에 제주 2박 3일 여행 같이 가실 분 구합니다.",
        "preferred_age_min": 20,
        "preferred_age_max": 30,
        "preferred_gender": "any",
        "region": "제주도",
        "travel_start_date": date(2026, 7, 10),
        "travel_end_date": date(2026, 7, 12),
        "companion_type": "friend",
        "image_urls": [],
    }
    base.update(overrides)
    return base


@pytest.mark.unit
@pytest.mark.parametrize("cls", [CreatePostRequest, UpdatePostRequest])
class TestPostRangeValidation:
    def test_valid_payload_passes(self, cls):
        cls(**_payload())

    def test_age_min_equal_max_allowed(self, cls):
        cls(**_payload(preferred_age_min=25, preferred_age_max=25))

    def test_age_min_over_max_rejected(self, cls):
        with pytest.raises(ValidationError, match="선호 나이"):
            cls(**_payload(preferred_age_min=40, preferred_age_max=30))

    def test_travel_start_equal_end_allowed(self, cls):
        same_day = date(2026, 7, 10)
        cls(**_payload(travel_start_date=same_day, travel_end_date=same_day))

    def test_travel_start_after_end_rejected(self, cls):
        with pytest.raises(ValidationError, match="여행 시작일"):
            cls(**_payload(
                travel_start_date=date(2026, 7, 20),
                travel_end_date=date(2026, 7, 12),
            ))
