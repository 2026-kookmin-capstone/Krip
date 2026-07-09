"""Keyset(커서) 페이지네이션 공통 유틸.

커서를 `(정렬키 datetime, tiebreak id)` 로 인코딩한 opaque base64url 토큰으로 다룬다.
정렬키를 토큰 자체에 담으므로 커서 row 가 삭제돼도 재조회(scalar_subquery)가 필요 없어,
"커서 row 삭제 시 서브쿼리가 NULL → 남은 데이터가 있어도 빈 페이지로 조기 종료" 되던
결함이 사라진다.

정렬은 `(sort_col DESC, id_col DESC)` 고정. 정렬키는 timezone-aware datetime 전제.

모든 커서는 서버가 발급한 이 토큰뿐이다. `decode_cursor` 가 None(손상/위조 토큰)이면
호출측이 `ValueError` 로 거부(→ 라우터 400)한다.
"""
import base64
import binascii
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, or_


# base64 decode 로 우연히 뽑히기 어려운 제어문자 구분자 + 버전 태그로 구 원시 ID 오판독 방지.
_SEP = "\x1f"
_VERSION = "v1"


def encode_cursor(sort_value: datetime, tiebreak_id: str) -> str:
    """`(정렬키, id)` → opaque base64url 토큰."""
    raw = _SEP.join([_VERSION, sort_value.isoformat(), tiebreak_id])
    return base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")


def decode_cursor(token: str) -> Optional[tuple[datetime, str]]:
    """토큰 → `(datetime, id)`. 복합 토큰이 아니면(구 원시 ID 등) None."""
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii")).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        return None
    # maxsplit=2 — id 에 구분자가 들어가도 마지막 조각으로 온전히 보존 (version/isoformat 은 안전).
    parts = raw.split(_SEP, 2)
    if len(parts) != 3 or parts[0] != _VERSION:
        return None
    try:
        sort_value = datetime.fromisoformat(parts[1])
    except ValueError:
        return None
    return sort_value, parts[2]


def keyset_where(sort_col, id_col, sort_value: datetime, id_value: str):
    """`(sort_col DESC, id_col DESC)` 정렬용 keyset 비교 조건."""
    return or_(
        sort_col < sort_value,
        and_(sort_col == sort_value, id_col < id_value),
    )
