"""Feed 도메인 전용 커스텀 예외.

Router 가 HTTPException 으로 매핑 (도메인 컨벤션):
    ValueError                      → 400
    PermissionError                 → 403  (본인 게시물이 아님 — Python builtin 사용, tripmate 패턴)
    FeedBlockedError                → 403  (PermissionError 하위 — 차단 관계 명시 위해 분리)
    FeedNotFoundError               → 404  (게시물 미존재 / visibility 미충족)
    FeedPostCommentNotFoundError    → 404  (댓글 미존재 / post 매칭 실패)
    PopupTargetNotFoundError        → 404  (popup 대상 user 미존재 / 회원가입 미완료)
"""


class FeedNotFoundError(ValueError):
    """존재하지 않는 게시물 — Router 에서 404 로 매핑.

    삭제된 게시물에 대한 단건 조회 / 수정 / 삭제 / 가시성 변경 등에서 발생.
    `access.load_viewable_post` 가 visibility 미충족 케이스도 본 예외로 일원화 (정보 누출 회피).
    """


class FeedBlockedError(PermissionError):
    """양방향 차단 관계 — Router 에서 403 으로 매핑.

    `PermissionError` 의 하위 — 라우터의 기존 `except PermissionError` 가 그대로 catch
    하면서, "본인 게시물 아님" 과 의미적으로 분리해 메시지/테스트에서 식별 가능하게 한다.
    `get_user_feed` / `load_viewable_post` 진입 시 viewer↔owner 어느 방향이든 차단이 있으면 발생.
    """


class FeedPostCommentNotFoundError(ValueError):
    """존재하지 않는 댓글 — Router 에서 404 로 매핑.

    `FeedNotFoundError` 와 분리 (둘 다 ValueError 하위지만 의미 분기). 라우터가 명시적
    catch 하면 메시지/로깅에서 "게시물" / "댓글" 구분 가능. `delete_comment` 의 post_id
    mismatch 도 본 예외로 일원화 (enumeration 차단).
    """


class PopupTargetNotFoundError(ValueError):
    """popup 대상 유저 미존재 — Router 에서 404 로 매핑.

    `GET /feed/popup/{user_id}` 진입 시 user 자체가 없거나 (탈퇴 등), `user_detail_inform`
    이 결손 (2차 회원가입 미완료) 인 경우 발생. user 존재/회원가입 상태가 노출되지 않도록
    두 케이스 모두 본 예외 한 가지로 일원화 (`get_my_profile` 의 ProfileNotRegisteredError
    와 별개 — popup 은 타 유저 진입점이라 enumeration 회피 우선).
    """
