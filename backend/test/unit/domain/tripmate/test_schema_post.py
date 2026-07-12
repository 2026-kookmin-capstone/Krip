"""여행메이트 게시글 schema(app.domain.tripmate.schema.tripmate_post) 검증 테스트.

_validate_post_ranges 교차 검증(나이 하한≤상한 / 여행 시작≤종료)이 DB CheckConstraint(500)
대신 요청 단계 ValidationError(422)로 걸러지는지 회귀 가드. Create/Update 양쪽 동일 적용.
"""
from datetime import date

import pytest
from pydantic import ValidationError

from app.domain.tripmate.model.tripmate_post import CompanionType, PreferredGender
from app.domain.tripmate.schema.tripmate_post import (
    _MAX_IMAGE_URL_LEN,
    _MAX_POST_IMAGES,
    CreatePostRequest,
    SaveDraftRequest,
    UpdatePostRequest,
)


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


# 이미지 URL 상한은 Mongo draft 팽창과 목록 조회 폭증을 제한한다.
@pytest.mark.unit
@pytest.mark.parametrize("cls", [CreatePostRequest, UpdatePostRequest])
class TestPostImageLimits:
    def test_at_cap_allowed(self, cls):
        cls(**_payload(image_urls=[f"https://img/{i}" for i in range(_MAX_POST_IMAGES)]))

    def test_over_cap_rejected(self, cls):
        with pytest.raises(ValidationError):
            cls(**_payload(image_urls=[f"https://img/{i}" for i in range(_MAX_POST_IMAGES + 1)]))

    def test_too_long_url_rejected(self, cls):
        with pytest.raises(ValidationError):
            cls(**_payload(image_urls=["x" * (_MAX_IMAGE_URL_LEN + 1)]))


@pytest.mark.unit
class TestDraftImageLimits:
    def test_at_cap_allowed(self):
        SaveDraftRequest(image_urls=[f"https://img/{i}" for i in range(_MAX_POST_IMAGES)])

    def test_over_cap_rejected(self):
        with pytest.raises(ValidationError):
            SaveDraftRequest(image_urls=[f"https://img/{i}" for i in range(_MAX_POST_IMAGES + 1)])

    def test_too_long_url_rejected(self):
        with pytest.raises(ValidationError):
            SaveDraftRequest(image_urls=["x" * (_MAX_IMAGE_URL_LEN + 1)])


# 임시저장 enum 제약 — free-form str 이면 임의 값이 Mongo 에 저장·복원되고
# 게시 시점에야 422 로 터진다. 입력 단계에서 enum 으로 걸러지는지 회귀 가드.

@pytest.mark.unit
class TestDraftEnumValidation:
    def test_valid_enum_values_allowed(self):
        req = SaveDraftRequest(preferred_gender="any", companion_type="friend")
        assert req.preferred_gender == PreferredGender.ANY
        assert req.companion_type == CompanionType.FRIEND

    def test_none_allowed_partial_draft(self):
        # 드래프트는 부분 저장이므로 미입력(None) 허용
        req = SaveDraftRequest()
        assert req.preferred_gender is None
        assert req.companion_type is None

    def test_bad_preferred_gender_rejected(self):
        with pytest.raises(ValidationError):
            SaveDraftRequest(preferred_gender="attack-helicopter")

    def test_bad_companion_type_rejected(self):
        with pytest.raises(ValidationError):
            SaveDraftRequest(companion_type="stranger")
