"""PlaceRepository._parse_cursor 커서 파싱 검증 회귀 테스트.

커서는 "거리:place_id" 형식이며, 손상되거나 비유한(nan/inf) 값은 조용한 빈 페이지
($match NaN)·정의되지 않은 동작($geoNear minDistance=inf)을 유발한다. 이런 입력이
raw Python 에러가 아니라 도메인 표준 ValueError("유효하지 않은 커서입니다.")로 거부되어
라우터가 400(일반 메시지)으로 매핑되는지 가드한다.
"""
import pytest

from app.domain.tour.repository.place import PlaceRepository


@pytest.mark.unit
class TestParseCursor:
    def test_valid_cursor_parsed(self):
        distance, place_id = PlaceRepository._parse_cursor("123.45:PLACE_abc")
        assert distance == 123.45
        assert place_id == "PLACE_abc"

    def test_place_id_with_colon_kept(self):
        distance, place_id = PlaceRepository._parse_cursor("10:PLACE:x:y")
        assert distance == 10.0
        assert place_id == "PLACE:x:y"

    @pytest.mark.parametrize("bad", ["nan:PLACE_a", "NaN:PLACE_a", "inf:PLACE_a", "-inf:PLACE_a", "Infinity:PLACE_a"])
    def test_non_finite_distance_rejected(self, bad):
        with pytest.raises(ValueError, match="유효하지 않은 커서"):
            PlaceRepository._parse_cursor(bad)

    @pytest.mark.parametrize("bad", ["no-colon-here", "abc:PLACE_a", "12.3:", ":PLACE_a", ""])
    def test_malformed_cursor_rejected(self, bad):
        with pytest.raises(ValueError, match="유효하지 않은 커서"):
            PlaceRepository._parse_cursor(bad)
