"""TranslationService vendor 예외 매핑 단위 테스트.

핵심 regression: Papago 429(쿼터 소진)를 502(VendorError)로 뭉개면 클라이언트가 서버 장애로
오인해 즉시 재시도 → 쿼터 소진 지속. 429 를 QuotaExceededError 로 분리해 백오프를 유도한다.
"""
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import HTTPException, Request
from loguru import logger

from app.domain.translation.router.translation import detect_language
from app.domain.translation.schema.translation import DetectRequest
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
    async def test_vendor_error_router_log_preserves_only_bounded_code(self, tmp_path):
        secret = "PRIVATE_VENDOR_ERROR_MESSAGE_7X9@example.com"
        log_path = tmp_path / "translation.jsonl"
        vendor_request = httpx.Request("POST", "https://papago.example/api")
        response = httpx.Response(
            400,
            request=vendor_request,
            text=(
                '{"errorCode":"N2MT05","errorMessage":"'
                f'{secret}"}}'
            ),
        )
        service = _service_detect_raising(
            httpx.HTTPStatusError("400", request=vendor_request, response=response)
        )
        sink_id = logger.add(log_path, serialize=True)
        try:
            with pytest.raises(HTTPException) as caught:
                await detect_language(
                    request=Request({"type": "http"}),
                    body=DetectRequest(text="안녕"),
                    translation_service=service,
                )
        finally:
            logger.remove(sink_id)

        raw_log = log_path.read_text(encoding="utf-8")
        records = [
            json.loads(line)["record"] for line in raw_log.splitlines()
        ]
        vendor_records = [
            record for record in records
            if record["extra"].get("logger_name") == "translation"
            and record["message"] == "Translation vendor request failed"
        ]
        assert caught.value.status_code == 502
        assert len(vendor_records) == 1
        assert vendor_records[0]["extra"] == {
            "logger_name": "translation",
            "provider": "papago",
            "operation": "detect",
            "vendor_status": 400,
            "vendor_code": "N2MT05",
        }
        assert secret not in raw_log

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

    async def test_vendor_error_code_is_extracted_without_body(self):
        req = httpx.Request("POST", "https://papago.example/api")
        resp = httpx.Response(
            400, request=req,
            text='{"errorCode":"N2MT05","errorMessage":"secret detail with PII"}',
        )
        svc = _service_detect_raising(
            httpx.HTTPStatusError("400", request=req, response=resp)
        )

        with pytest.raises(TranslationVendorError) as caught:
            await svc.detect("안녕")

        assert caught.value.vendor_code == "N2MT05"
        assert "secret detail" not in str(caught.value)
        assert not hasattr(caught.value, "body")

    async def test_vendor_error_code_is_none_for_unparseable_body(self):
        svc = _service_detect_raising(_http_status_error(500))

        with pytest.raises(TranslationVendorError) as caught:
            await svc.detect("안녕")

        assert caught.value.vendor_code is None

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
