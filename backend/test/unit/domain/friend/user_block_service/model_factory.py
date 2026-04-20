"""UserBlockService 전용 팩토리.

FriendshipService 테스트에서 쓰던 팩토리를 그대로 재사용하면 모듈 경계가
섞이기 쉽기에, 같은 구현을 간단히 re-export 한다.
"""

from test.unit.domain.friend.friendship_service.model_factory import (
    FriendshipFactory,
    UserBlockFactory,
    UserFactory,
)


__all__ = ["FriendshipFactory", "UserBlockFactory", "UserFactory"]
