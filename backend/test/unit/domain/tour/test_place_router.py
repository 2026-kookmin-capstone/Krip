"""장소 조회 라우터 keyword 쿼리 파라미터 상한 회귀 테스트.

keyword 는 인덱스 못 타는 $regex 로 전체 컬렉션을 스캔하고 tour_search_history 에
그대로 저장되므로 길이 상한이 필수. 상한을 넘긴 keyword 가 FastAPI 검증에서 422 로
거부되는지, 실제 라우터 함수 시그니처의 Query 제약을 그대로 재사용해 확인한다.
"""
import inspect
from typing import Optional

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.tour.router.place import get_places


# 실제 라우터 함수 시그니처에서 keyword 의 Query 기본값(제약 포함)을 그대로 추출.
_KEYWORD_QUERY = inspect.signature(get_places).parameters["keyword"].default
_MAX_LEN = next(m.max_length for m in _KEYWORD_QUERY.metadata if hasattr(m, "max_length"))


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/probe")
    def _probe(keyword: Optional[str] = _KEYWORD_QUERY):
        return {"keyword": keyword}

    return TestClient(app)


@pytest.mark.unit
class TestPlaceKeywordMaxLength:
    def test_max_length_is_50(self):
        assert _MAX_LEN == 50

    def test_at_max_allowed(self):
        r = _client().get("/probe", params={"keyword": "가" * _MAX_LEN})
        assert r.status_code == 200

    def test_over_max_rejected(self):
        r = _client().get("/probe", params={"keyword": "가" * (_MAX_LEN + 1)})
        assert r.status_code == 422

    def test_empty_keyword_rejected(self):
        # min_length=1 은 유지되어야 한다.
        r = _client().get("/probe", params={"keyword": ""})
        assert r.status_code == 422
