"""Tour 도메인 전용 커스텀 예외.

Router 가 HTTPException 으로 매핑 (§에러 처리 컨벤션):
    ValueError                  → 400 (또는 endpoint 에 따라 404)
    PermissionError             → 403
    TourPlanNotFoundError       → 404 (plan_id 로 직접 조회한 plan 이 없음)
    TourPlanItemNotFoundError   → 404 (카드/플랜/URL 계층 불일치 모두 404 통일)
"""


class TourPlanNotFoundError(ValueError):
    """플랜을 찾을 수 없음 — Router 에서 404 로 매핑.

    plan_id 로 직접 조회했는데 row 가 없는 경우 (혹은 race 로 사라짐).
    plan-not-found 와 비즈니스 검증 (day_number 범위 등) 을 같은 endpoint 에서
    raise 하면 매핑이 갈리는데, 이 클래스로 분리하여 라우터가 404 / 400 분기 가능.
    """


class TourPlanItemNotFoundError(ValueError):
    """카드를 찾을 수 없음 — Router 에서 404 로 매핑.

    다음 세 케이스를 통합:
    - item_id 가 존재하지 않음
    - item 은 있는데 소속 plan 이 사라짐 (race)
    - URL 의 plan_id 와 item.plan_id 가 불일치 (URL 계층 위반)

    리소스 enumeration 방어를 위해 메시지는 모두 "존재하지 않는 카드입니다." 로 통일.
    """
