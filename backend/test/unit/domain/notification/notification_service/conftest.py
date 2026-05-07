"""NotificationService 단위 테스트 fixtures.

NotificationService 는 RDB 의존성 없는 stateless service — UoW / session 받지 않음.
NotificationRepository (motor 기반) 만 mock 으로 치환하면 모든 메서드 검증 가능.

`Notification` Document 클래스 자체도 stub 으로 치환 — service 의 fan-out 메서드가
`Notification(...)` 으로 직접 인스턴스화하는데, `init_beanie` 미호출 환경에서는
`CollectionWasNotInitialized` 가 raise 됨. mongo 비접근 단위 테스트라 stub 으로 우회.
"""
from datetime import datetime, timezone

from beanie import PydanticObjectId
import pytest

from app.domain.notification.service.notification import NotificationService

from test.unit.domain.notification.mock_factory import NotificationRepositoryMockFactory
from test.unit.domain.notification.notification_service.model_factory import (
    NotificationFactory,
)


# Notification Document 의 pydantic field default — stub 도 동일하게 모방하여
# service 의 fan-out 결과를 진짜 Document 처럼 검증할 수 있게 한다.
_NOTIFICATION_FIELD_DEFAULTS = {
    "comment_id": None,
    "actor_profile_image_url": None,
    "target_preview": None,
    "comment_preview": None,
    "display": True,
    "read_at": None,
}


class _NotificationStub:
    """`Notification` Document 의 lightweight 대체 — 단위 테스트 전용.

    keyword-only 인스턴스화 → attribute 보유. 누락된 keyword 는 model 의 pydantic default
    를 모방해서 채움 (`comment_id=None` 등). `id` 자동 부여 (`_to_dto` 의 `str(n.id)` 대비),
    `created_at` 도 default_factory 모방.
    """

    def __init__(self, **kwargs):
        for k, v in _NOTIFICATION_FIELD_DEFAULTS.items():
            setattr(self, k, v)
        for k, v in kwargs.items():
            setattr(self, k, v)
        if not hasattr(self, "id") or self.id is None:
            self.id = PydanticObjectId()
        if not hasattr(self, "created_at") or self.created_at is None:
            self.created_at = datetime.now(timezone.utc)


@pytest.fixture
def notification_repo_mock():
    return NotificationRepositoryMockFactory.create()


@pytest.fixture
def service(monkeypatch, notification_repo_mock):
    """NotificationRepository + Notification Document 을 stub 으로 치환한 service.

    - `NotificationService.__init__` 의 `self.repo = NotificationRepository()` → mock 반환.
    - service 가 호출하는 `Notification(...)` 은 `_NotificationStub` 으로 대체되어
      mongo init 없이도 fan-out 흐름이 동작. mock repo 가 이 stub 을 그대로 받음.
    """
    monkeypatch.setattr(
        "app.domain.notification.service.notification.NotificationRepository",
        lambda: notification_repo_mock,
    )
    monkeypatch.setattr(
        "app.domain.notification.service.notification.Notification",
        _NotificationStub,
    )
    return NotificationService()


@pytest.fixture(autouse=True)
def reset_factories():
    """ID counter 격리 — 테스트 간 의존 방지."""
    NotificationFactory.reset_counter()
    yield
    NotificationFactory.reset_counter()
