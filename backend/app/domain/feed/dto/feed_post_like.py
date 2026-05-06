"""피드 좋아요 DTO — 서비스 → 라우터 경계.

`add/remove_like` 의 like_count 는 primitive (int) 흐름이라 DTO 불필요. 좋아요 누른 유저
목록만 프로필 정보 포함이라 DTO 로 노출. 서비스가 SQLAlchemy 모델을 직접 라우터로 흘리지
않게 하는 도메인 컨벤션 일치.
"""
from typing import Optional
from dataclasses import dataclass


@dataclass
class LikedUserData:
    """좋아요 누른 유저 응답 DTO — `find_with_user_by_post` 의 단일 JOIN 결과를 매핑.

    `user_name` 은 `user_detail_inform.user_name` 를 가져오되, detail 결손 (회원가입 미완료
    등 비정상 상태) 시 빈 문자열 fallback — chat 도메인 컨벤션 (`_user_to_member_dto`).
    `profile_image_url` 도 동일하게 None fallback.
    """
    user_id: str
    user_name: str
    profile_image_url: Optional[str]
