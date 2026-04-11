"""
Tripmate 도메인 Object Storage prefix 정의

경로 구조:
  uploads/perm/{user_id}/threads/          - 채팅 쓰레드 이미지
  uploads/perm/{user_id}/posts/{post_id}/  - 게시글 이미지
"""


def post_prefix(user_id: str, post_id: str) -> str:
    """게시글 이미지 prefix"""
    return f"{user_id}/posts/{post_id}"


def thread_prefix(user_id: str) -> str:
    """채팅 쓰레드 이미지 prefix"""
    return f"{user_id}/threads"
