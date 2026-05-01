"""Tour 도메인 전용 커스텀 예외.

Router 가 HTTPException 으로 매핑 (§에러 처리 컨벤션):
    ValueError                  → 400 (또는 endpoint 에 따라 404)
    PermissionError             → 403
    TourPlanItemNotFoundError   → 404 (카드/플랜/URL 계층 불일치 모두 404 통일)
"""


class TourPlanItemNotFoundError(ValueError):
    """카드를 찾을 수 없음 — Router 에서 404 로 매핑.

    다음 세 케이스를 통합:
    - item_id 가 존재하지 않음
    - item 은 있는데 소속 plan 이 사라짐 (race)
    - URL 의 plan_id 와 item.plan_id 가 불일치 (URL 계층 위반)

    리소스 enumeration 방어를 위해 메시지는 모두 "존재하지 않는 카드입니다." 로 통일.
    """
