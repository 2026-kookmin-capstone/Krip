"""Feed 도메인 전용 커스텀 예외.

Router 가 HTTPException 으로 매핑 (도메인 컨벤션):
    ValueError              → 400
    PermissionError         → 403  (본인 게시물이 아님 — Python builtin 사용, tripmate 패턴)
    FeedNotFoundError       → 404
"""


class FeedNotFoundError(ValueError):
    """존재하지 않는 게시물 — Router 에서 404 로 매핑.

    삭제된 게시물에 대한 단건 조회 / 수정 / 삭제 / 가시성 변경 등에서 발생.
    """
