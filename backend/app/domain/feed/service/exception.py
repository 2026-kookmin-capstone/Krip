"""Feed 도메인 전용 커스텀 예외.

Router 가 HTTPException 으로 매핑 (도메인 컨벤션):
    ValueError              → 400
    PermissionError         → 403  (본인 게시물이 아님 — Python builtin 사용, tripmate 패턴)
    FeedBlockedError        → 403  (PermissionError 하위 — 차단 관계 명시 위해 분리)
    FeedNotFoundError       → 404
"""


class FeedNotFoundError(ValueError):
    """존재하지 않는 게시물 — Router 에서 404 로 매핑.

    삭제된 게시물에 대한 단건 조회 / 수정 / 삭제 / 가시성 변경 등에서 발생.
    """


class FeedBlockedError(PermissionError):
    """양방향 차단 관계 — Router 에서 403 으로 매핑.

    `PermissionError` 의 하위 — 라우터의 기존 `except PermissionError` 가 그대로 catch
    하면서, "본인 게시물 아님" 과 의미적으로 분리해 메시지/테스트에서 식별 가능하게 한다.
    `get_user_feed` 진입 시 viewer↔owner 어느 방향이든 차단이 있으면 발생.
    """
