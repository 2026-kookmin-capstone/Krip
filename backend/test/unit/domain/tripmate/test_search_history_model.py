"""TripmateSearchHistory 모델 — read-back 안전성.

regression: 모델 search_name 에 max_length=50 을 걸면 save() 의 raw motor $set 은 못 막으면서
(write 미방어), 상한 도입 전 저장된 50자 초과 legacy row 를 find_by_user_id 로 읽을 때
Beanie 검증이 ValidationError→500 을 낸다. write 상한은 라우터가 강제하므로 모델엔 max_length
을 두지 않아 legacy row 도 안전하게 read-back 되어야 한다.
"""
import annotated_types
import pytest

from app.domain.tripmate.model.tripmate_search_history import TripmateSearchHistory


pytestmark = pytest.mark.unit


def test_search_name_has_no_max_length_constraint():
    """search_name 에 max_length 제약이 없어야 legacy >50자 row 를 read-back 시 500 이 안 난다."""
    field = TripmateSearchHistory.model_fields["search_name"]
    max_len_constraints = [
        m for m in field.metadata if isinstance(m, annotated_types.MaxLen)
    ]
    assert not max_len_constraints, (
        f"search_name 에 max_length 제약이 남아있음: {max_len_constraints} — "
        "raw motor write 는 못 막으면서 legacy row read-back 500 만 유발한다."
    )
