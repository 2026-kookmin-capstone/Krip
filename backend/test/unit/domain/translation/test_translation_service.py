"""TranslationService vendor 예외 매핑 단위 테스트.

핵심 regression: Papago 429(쿼터 소진)를 502(VendorError)로 뭉개면 클라이언트가 서버 장애로
오인해 즉시 재시도 → 쿼터 소진 지속. 429 를 QuotaExceededError 로 분리해 백오프를 유도한다.
"""
from unittest.mock import AsyncMock

import httpx
import pytest

from app.domain.translation.service.exception import (
    TranslationQuotaExceededError,
    TranslationUnreachableError,
    TranslationVendorError,
)
from app.domain.translation.service.translation import TranslationService


pytestmark = pytest.mark.unit


def _http_status_error(status_code: int) -> httpx.HTTPStatusError:
    req = httpx.Request("POST", "https://papago.example/api")
    resp = httpx.Response(status_code, request=req, text=f"body-{status_code}")
    return httpx.HTTPStatusError(f"{status_code}", request=req, response=resp)


def _service_detect_raising(exc: Exception) -> TranslationService:
    svc = TranslationService()
    svc._translator = AsyncMock()
    svc._translator.detect = AsyncMock(side_effect=exc)
    svc._translator.translate = AsyncMock(side_effect=exc)
    return svc


class TestTranslationExceptionMapping:
    async def test_429_maps_to_quota_exceeded_detect(self):
        svc = _service_detect_raising(_http_status_error(429))
        with pytest.raises(TranslationQuotaExceededError) as caught:
            await svc.detect("안녕")
        assert "body-429" not in str(caught.value)
        assert not hasattr(caught.value, "body")

    async def test_429_maps_to_quota_exceeded_translate(self):
        svc = _service_detect_raising(_http_status_error(429))
        with pytest.raises(TranslationQuotaExceededError):
            await svc.translate("안녕", "ko", "en")

    async def test_500_maps_to_vendor_error(self):
        svc = _service_detect_raising(_http_status_error(500))
        with pytest.raises(TranslationVendorError) as caught:
            await svc.detect("안녕")
        assert caught.value.status_code == 500
        assert "body-500" not in str(caught.value)
        assert not hasattr(caught.value, "body")

    async def test_400_maps_to_vendor_error(self):
        svc = _service_detect_raising(_http_status_error(400))
        with pytest.raises(TranslationVendorError):
            await svc.translate("안녕", "ko", "en")

    async def test_request_error_maps_to_unreachable(self):
        req = httpx.Request("POST", "https://papago.example/api")
        svc = _service_detect_raising(httpx.ConnectError("no route", request=req))
        with pytest.raises(TranslationUnreachableError) as caught:
            await svc.detect("안녕")
        assert "no route" not in str(caught.value)

    async def test_malformed_payload_maps_to_vendor_error(self):
        svc = _service_detect_raising(KeyError("message"))
        with pytest.raises(TranslationVendorError):
            await svc.detect("안녕")

    async def test_malformed_payload_typeerror_maps_to_vendor_error_detect(self):
        # 200 body 가 dict 가 아니거나 중간 노드가 None/str 이면 nested 접근이 TypeError.
        # 예: payload=None 이면 payload["langCode"] → TypeError. 500 아닌 502 로 흡수해야 한다.
        svc = _service_detect_raising(TypeError("'NoneType' object is not subscriptable"))
        with pytest.raises(TranslationVendorError):
            await svc.detect("안녕")

    async def test_malformed_payload_typeerror_maps_to_vendor_error_translate(self):
        svc = _service_detect_raising(TypeError("'NoneType' object is not subscriptable"))
        with pytest.raises(TranslationVendorError):
            await svc.translate("안녕", "ko", "en")
