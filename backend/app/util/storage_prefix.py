"""
도메인 Object Storage prefix 정의

경로 구조:
  uploads/perm/{user_id}/posts/{uuid}.{ext}    - 게시글 이미지
  uploads/perm/{user_id}/threads/{uuid}.{ext}  - 채팅 쓰레드 이미지
  uploads/perm/{user_id}/profile/{uuid}.{ext}  - 프로필 이미지

탈퇴 시 `delete_by_prefix(user_id)` 가 `uploads/perm/{user_id}/*` 전체를 정리하므로
모든 prefix 의 첫 segment 는 `user_id` 로 통일한다.
"""


def post_prefix(user_id: str) -> str:
    """게시글 이미지 prefix"""
    return f"{user_id}/posts"


def thread_prefix(user_id: str) -> str:
    """채팅 쓰레드 이미지 prefix"""
    return f"{user_id}/threads"


def profile_prefix(user_id: str) -> str:
    """프로필 이미지 prefix (유저당 1장 정책)"""
    return f"{user_id}/profile"
