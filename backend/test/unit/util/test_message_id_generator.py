"""채팅 메시지 ID 생성기 회귀 테스트.

검증:
    - prefix 가 약속된 값 (MSG_) — MongoDB _id / RDB chat_room.last_message_id 호환성 보장
    - 형식: MSG_{timestamp(int)}_{16hex} — 랜덤 성분을 64bit 로 확대해 _id 충돌 방지
      (_id 는 insert-retry 에서 재발급되지 않으므로 32bit 는 고부하 시 충돌 → 송신 500)
    - timestamp prefix 라 문자열 정렬 = 시간순 (DocString 명시 약속, 랜덤 suffix 는 tie-break 만)
    - 길이가 chat_room.last_message_id String(50) 상한 이내

포맷/정렬 계약을 유지하면서 엔트로피만 키운다.
"""
import re

import pytest

from app.util.id_generator import generate_message_id


# 랜덤 성분이 16 hex(64bit) 이상임을 강제 — 8hex 로 되돌아가면(엔트로피 회귀) 실패.
_MSG_PATTERN = re.compile(r"^MSG_(\d+)_([0-9a-f]{16})$")

_LAST_MESSAGE_ID_COLUMN_LEN = 50  # chat_room.last_message_id = Column(String(50))


@pytest.mark.unit
class TestGenerateMessageId:
    def test_prefix_is_MSG(self):
        assert generate_message_id().startswith("MSG_")

    def test_format_matches_pattern(self):
        assert _MSG_PATTERN.match(generate_message_id())

    def test_random_component_has_high_entropy(self):
        """랜덤 성분이 16 hex(64bit) 이상 — 32bit(8hex) 로의 엔트로피 회귀 가드."""
        match = _MSG_PATTERN.match(generate_message_id())
        assert match is not None
        random_hex = match.group(2)
        assert len(random_hex) >= 16

    def test_fits_last_message_id_column(self):
        """MSG_ id 는 RDB chat_room.last_message_id String(50) 에도 저장되므로 길이 상한 준수."""
        assert len(generate_message_id()) <= _LAST_MESSAGE_ID_COLUMN_LEN

    def test_n_calls_are_all_unique(self):
        ids = {generate_message_id() for _ in range(1000)}
        assert len(ids) == 1000

    def test_timestamp_prefix_preserves_sort_order(self):
        """같은 초 내 랜덤 suffix 가 tie-break 만 담당 — timestamp 가 1차 정렬 키.

        더 큰 timestamp 는 랜덤 suffix 와 무관하게 항상 문자열 정렬에서 뒤에 온다.
        """
        low = "MSG_1783000000_ffffffffffffffff"   # 이른 시각 + 최대 suffix
        high = "MSG_1783000001_0000000000000000"  # 늦은 시각 + 최소 suffix
        assert low < high
