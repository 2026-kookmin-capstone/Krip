"""`_normalize_caption` 정규화 규칙 회귀 테스트.

POST(업로드) / PATCH(수정) 두 진입점이 같은 helper 를 호출 — DB 에 빈 문자열 caption row 가
생기지 않는다는 불변식이 깨지지 않는지 검증한다.

규칙:
    - None / "" / 공백만 → None  ("캡션 없음" 의 단일 표준 표현)
    - 비-빈 문자열은 leading/trailing 공백 포함 그대로 보존 (over-trimming 회피)
"""
import pytest

from app.domain.feed.service.feed_post import _normalize_caption


@pytest.mark.unit
class TestBlankCoercedToNone:
    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            " ",
            "   ",
            "\n",
            "\t",
            "  \n  \t  ",
        ],
    )
    def test_blank_returns_none(self, value):
        assert _normalize_caption(value) is None


@pytest.mark.unit
class TestNonBlankPreserved:
    @pytest.mark.parametrize(
        "value",
        [
            "hello",
            "안녕하세요",
            "  hello  ",   # leading/trailing 공백 보존 — 의도된 입력일 수 있음
            "line1\nline2",
            "a",
        ],
    )
    def test_non_blank_returned_as_is(self, value):
        assert _normalize_caption(value) == value
