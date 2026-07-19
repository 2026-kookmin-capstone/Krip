"""RecommendService vendor 예외 매핑 단위 테스트.

핵심 regression: ChatGoogleGenerativeAIError 는 GoogleAPICallError 를 상속하지 않아
(순수 Exception) 별도 매핑이 없으면 500 으로 누출됐다. 토큰 한도 초과 등 InvalidArgument 를
감싼 vendor 입력 거부를 502(VendorError)로 매핑하는지 검증.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from google.api_core.exceptions import (
    GoogleAPICallError,
    PermissionDenied,
    ResourceExhausted,
    Unauthenticated,
)
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

from app.domain.tour.service.exception import (
    TourRecommendCredentialExpiredError,
    TourRecommendQuotaExceededError,
    TourRecommendVendorError,
)
from app.domain.tour.service.recommend import RecommendService


def _service_raising(exc: Exception) -> RecommendService:
    svc = RecommendService()
    svc._planner = AsyncMock()
    svc._planner.invoke = AsyncMock(side_effect=exc)
    return svc


_BODY = SimpleNamespace(travel_days=1, food_preference=None, days=[])


@pytest.mark.unit
class TestRecommendExceptionMapping:
    async def test_chat_gemini_error_maps_to_vendor_error(self):
        svc = _service_raising(ChatGoogleGenerativeAIError("Invalid argument: token limit"))
        with pytest.raises(TourRecommendVendorError):
            await svc.recommend(_BODY)

    async def test_resource_exhausted_maps_to_quota(self):
        svc = _service_raising(ResourceExhausted("quota"))
        with pytest.raises(TourRecommendQuotaExceededError):
            await svc.recommend(_BODY)

    async def test_unauthenticated_maps_to_credential_expired(self):
        svc = _service_raising(Unauthenticated("key revoked"))
        with pytest.raises(TourRecommendCredentialExpiredError):
            await svc.recommend(_BODY)

    async def test_permission_denied_maps_to_credential_expired(self):
        svc = _service_raising(PermissionDenied("no access"))
        with pytest.raises(TourRecommendCredentialExpiredError):
            await svc.recommend(_BODY)

    async def test_google_api_call_error_maps_to_vendor_error(self):
        svc = _service_raising(GoogleAPICallError("upstream 5xx"))
        with pytest.raises(TourRecommendVendorError):
            await svc.recommend(_BODY)
