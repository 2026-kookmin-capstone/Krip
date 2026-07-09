"""MenuOcrService vendor 예외 매핑 단위 테스트.

핵심 regression: ChatGoogleGenerativeAIError 는 GoogleAPICallError 를 상속하지 않아
(순수 Exception) 별도 매핑이 없으면 500 으로 누출됐다. 손상 이미지/토큰 한도 초과 등
InvalidArgument 를 감싼 vendor 입력 거부를 502(VendorError)로 매핑하는지 검증.
"""
from unittest.mock import AsyncMock

import pytest
from google.api_core.exceptions import (
    GoogleAPICallError,
    PermissionDenied,
    ResourceExhausted,
    Unauthenticated,
)
from langchain_google_genai.chat_models import ChatGoogleGenerativeAIError

from app.domain.menu_ai.service.exception import (
    MenuOcrCredentialExpiredError,
    MenuOcrQuotaExceededError,
    MenuOcrVendorError,
)
from app.domain.menu_ai.service.menu_ocr import MenuOcrService


def _service_raising(exc: Exception) -> MenuOcrService:
    svc = MenuOcrService()
    svc._ocr = AsyncMock()
    svc._ocr.invoke = AsyncMock(side_effect=exc)
    svc._ocr.invoke_batch = AsyncMock(side_effect=exc)
    return svc


@pytest.mark.unit
class TestMenuOcrExceptionMapping:
    async def test_chat_gemini_error_maps_to_vendor_error_single(self):
        svc = _service_raising(ChatGoogleGenerativeAIError("Invalid argument: bad image"))
        with pytest.raises(MenuOcrVendorError):
            await svc.ocr_single(b"x", "image/png")

    async def test_chat_gemini_error_maps_to_vendor_error_batch(self):
        svc = _service_raising(ChatGoogleGenerativeAIError("Invalid argument: bad image"))
        with pytest.raises(MenuOcrVendorError):
            await svc.ocr_batch([(b"x", "image/png")])

    async def test_resource_exhausted_maps_to_quota(self):
        svc = _service_raising(ResourceExhausted("quota"))
        with pytest.raises(MenuOcrQuotaExceededError):
            await svc.ocr_single(b"x", "image/png")

    async def test_unauthenticated_maps_to_credential_expired(self):
        svc = _service_raising(Unauthenticated("key revoked"))
        with pytest.raises(MenuOcrCredentialExpiredError):
            await svc.ocr_single(b"x", "image/png")

    async def test_permission_denied_maps_to_credential_expired(self):
        svc = _service_raising(PermissionDenied("no access"))
        with pytest.raises(MenuOcrCredentialExpiredError):
            await svc.ocr_single(b"x", "image/png")

    async def test_google_api_call_error_maps_to_vendor_error(self):
        svc = _service_raising(GoogleAPICallError("upstream 5xx"))
        with pytest.raises(MenuOcrVendorError):
            await svc.ocr_single(b"x", "image/png")
