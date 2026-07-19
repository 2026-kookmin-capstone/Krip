"""트립메이트 좋아요 DTO — 서비스 내부 transfer.

`add_like` 의 like_count 는 primitive (int) 흐름이라 응답 DTO 불필요. 본 모듈의
`AddLikePayload` 는 service 내부 transfer 객체 — 트랜잭션 (`_add_like_tx`) 이 합성하고
outer (`add_like`) 가 fan-out 호출에 사용. router 에 노출되지는 않지만 dto 디렉토리
일관성 위해 본 모듈에 둔다.

feed 도메인의 `AddLikePayload` 와 동일 시그니처지만 도메인 결합도 회피 위해 별도 정의 —
향후 도메인별 진화 (예: tripmate 가 추가 snapshot 필드 필요) 여지 보존.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class AddLikePayload:
    """좋아요 추가 service 내부 transfer.

    트랜잭션 안에서 합성 → 트랜잭션 밖 outer 가 fan-out 호출에 사용. router 에는
    `like_count` 만 노출되고 나머지 snapshot 필드는 InboxService 로만 전달.
    `recipient_id == actor_id` 면 outer 가 fan-out 자체를 skip → snapshot 필드는
    그 경우 더미 값 (트랜잭션 안에서 detail fetch 도 생략).
    """
    like_count: int
    recipient_id: str
    actor_name: str
    actor_profile_image_url: Optional[str]
    post_preview: Optional[str]
