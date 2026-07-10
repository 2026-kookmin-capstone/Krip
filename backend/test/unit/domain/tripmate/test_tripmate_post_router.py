"""여행메이트 검색 라우터 keyword 쿼리 파라미터 상한 회귀 테스트.

keyword 는 앵커 없는 ILIKE '%kw%' 로 제목/내용/닉네임을 스캔하고 search_name 으로
저장되므로 tour 검색과 동일하게 50자 상한이 필요. 상한 초과 keyword 가 FastAPI 검증에서
422 로 거부되는지, 실제 라우터 함수 시그니처의 Query 제약을 그대로 재사용해 확인한다.
"""
import inspect

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.domain.tripmate.router.tripmate_post import search_posts


# 실제 라우터 함수 시그니처에서 keyword 의 Query 기본값(제약 포함)을 그대로 추출.
_KEYWORD_QUERY = inspect.signature(search_posts).parameters["keyword"].default
_MAX_LEN = next(m.max_length for m in _KEYWORD_QUERY.metadata if hasattr(m, "max_length"))


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/probe")
    def _probe(keyword: str = _KEYWORD_QUERY):
        return {"keyword": keyword}

    return TestClient(app)


@pytest.mark.unit
class TestSearchKeywordMaxLength:
    def test_max_length_is_50(self):
        assert _MAX_LEN == 50

    def test_at_max_allowed(self):
        r = _client().get("/probe", params={"keyword": "가" * _MAX_LEN})
        assert r.status_code == 200

    def test_over_max_rejected(self):
        r = _client().get("/probe", params={"keyword": "가" * (_MAX_LEN + 1)})
        assert r.status_code == 422

    def test_missing_keyword_rejected(self):
        # keyword 는 필수(...) 이므로 미입력 시 422.
        r = _client().get("/probe")
        assert r.status_code == 422
