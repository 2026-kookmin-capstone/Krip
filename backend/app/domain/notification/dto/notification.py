"""알림 DTO — 서비스 → 라우터 경계.

Mongo `Notification` document 의 필드 중 `read_at` 은 boolean `is_read` 로 평탄화 —
클라이언트는 정확한 읽은 시각이 거의 필요 없고, 미읽음 강조 UI 만 결정. 응답 면적 축소.
"""
from typing import List, Optional
from dataclasses import dataclass
from datetime import datetime

from app.domain.notification.model.notification import NotificationType, TargetType


@dataclass
class NotificationData:
    """알림 단건 응답 DTO — 알림창 표시용 snapshot 포함.

    `actor_name` / `actor_profile_image_url` / `target_preview` / `comment_preview` 는
    알림 발생 시점에 박은 snapshot. 이후 actor 가 닉네임/프로필을 바꿔도 옛 알림은 옛 값 유지
    (이벤트 기록 정책). 클라이언트는 deep link 클릭 시 진짜 최신 데이터를 별도 fetch.
    """
    notification_id: str
    type: NotificationType
    actor_id: str
    actor_name: str
    actor_profile_image_url: Optional[str]
    target_type: TargetType
    target_id: str
    comment_id: Optional[str]
    target_preview: Optional[str]
    comment_preview: Optional[str]
    is_read: bool
    created_at: datetime


@dataclass
class NotificationListData:
    """알림 목록 응답 DTO — 커서 페이지네이션, 최신순.

    `next_cursor` 는 마지막 알림의 `created_at` ISO string. 더 없으면 None.
    """
    notifications: List[NotificationData]
    next_cursor: Optional[str]
