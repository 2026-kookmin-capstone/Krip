"""피드 좋아요 DTO — 서비스 → 라우터 경계 + 서비스 내부 transfer.

`add/remove_like` 의 like_count 는 primitive (int) 흐름이라 응답 DTO 불필요. 좋아요 누른
유저 목록만 프로필 정보 포함이라 DTO 로 노출. 서비스가 SQLAlchemy 모델을 직접 라우터로
흘리지 않게 하는 도메인 컨벤션 일치.

`AddLikePayload` 는 service 내부 transfer 객체 — 트랜잭션 (`_add_like_tx`) 가 합성하고
outer (`add_like`) 가 fan-out 호출에 사용. router 에 노출되지는 않지만 dto 디렉토리 일관성
위해 본 모듈에 함께 둔다.
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


@dataclass
class AddLikePayload:
    """좋아요 추가 service 내부 transfer.

    트랜잭션 안에서 합성 → 트랜잭션 밖 outer 가 fan-out 호출에 사용. router 에는
    `like_count` 만 노출되고 나머지 snapshot 필드는 NotificationService 로만 전달.
    `recipient_id == actor_id` 면 outer 가 fan-out 자체를 skip → snapshot 필드는
    그 경우 더미 값 (트랜잭션 안에서 detail fetch 도 생략).
    """
    like_count: int
    recipient_id: str
    actor_name: str
    actor_profile_image_url: Optional[str]
    post_preview: Optional[str]
