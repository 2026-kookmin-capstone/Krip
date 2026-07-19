"""커서 코덱(app.util.cursor) 단위 테스트.

- encode → decode 왕복 정확성 (datetime + id 보존, 마이크로초/tz 포함)
- 구 원시 ID 커서는 None 으로 판별되어 호출측 폴백을 태운다
- 손상/비정상 토큰도 None (예외 없이)
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.util.cursor import decode_cursor, encode_cursor


@pytest.mark.unit
class TestCursorCodec:
    def test_roundtrip_preserves_datetime_and_id(self):
        ts = datetime(2026, 7, 9, 1, 2, 3, 456789, tzinfo=timezone.utc)
        token = encode_cursor(ts, "FRIENDSHIP_1700000000_abcdef12")
        decoded = decode_cursor(token)
        assert decoded is not None
        got_ts, got_id = decoded
        assert got_ts == ts
        assert got_id == "FRIENDSHIP_1700000000_abcdef12"

    def test_roundtrip_preserves_non_utc_offset(self):
        kst = timezone(timedelta(hours=9))
        ts = datetime(2026, 7, 9, 10, 0, 0, tzinfo=kst)
        decoded = decode_cursor(encode_cursor(ts, "TMP_x"))
        assert decoded is not None
        # 같은 순간이면 == 참 (offset 표현 차이 무관)
        assert decoded[0] == ts

    def test_id_with_separator_or_special_chars(self):
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        # id 에 구분자/유니코드가 있어도 split(maxsplit) + base64 로 안전
        decoded = decode_cursor(encode_cursor(ts, "USER_a|b\x1fc"))
        assert decoded is not None and decoded[1] == "USER_a|b\x1fc"

    def test_legacy_raw_id_cursor_returns_none(self):
        # 구버전 커서(원시 ID)는 복합 토큰이 아니므로 None → 호출측 scalar_subquery 폴백
        assert decode_cursor("FRIENDSHIP_1700000000_abcdef12") is None
        assert decode_cursor("USER_1700000000_abcdef12") is None
        assert decode_cursor("TMP_test_0001") is None

    def test_malformed_tokens_return_none(self):
        assert decode_cursor("") is None
        assert decode_cursor("!!!not-base64!!!") is None
        assert decode_cursor("YWJj") is None  # base64 로 "abc" — 구분자/버전 없음
