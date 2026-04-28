"""Router 계층 HTTP 계약 테스트.

Service 를 Mock 으로 대체하고 FastAPI TestClient 로 라우터가:
- 성공 시 적절한 status code + JSON shape
- ValueError → 400, PermissionError → 403 매핑
- 요청 body 검증 실패 시 422
를 반환하는지 검증한다. 실 DB 가 필요 없어 POSTGRES_TEST_URL 없이도 실행된다.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from dependency_injector import providers
from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.database.model  # noqa: F401 — 매퍼 선 등록 (dto 가 enum 타입 참조)
from app.container import Container
from app.domain.auth.model.user_detail_inform import Gender
from app.domain.auth.model.user_travel_style import TravelStyle
from app.domain.friend.dto.friend_detail import FriendDetailData
from app.domain.friend.dto.friendship import (
    FriendPeerData,
    FriendshipData,
    FriendshipListData,
)
from app.domain.friend.dto.user_block import UserBlockData
from app.domain.friend.model.friendship import FriendshipStatus
from app.domain.friend.router import friend_router
from app.domain.friend.service.friend_detail import UserNotFoundError


pytestmark = pytest.mark.integration


# ──────────────────────────────────────────────────────────────────
# 공통 fixture
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def http():
    """Service 를 mock 으로 주입한 최소 FastAPI 앱 + TestClient."""
    container = Container()

    friendship_mock = AsyncMock()
    block_mock = AsyncMock()
    detail_mock = AsyncMock()

    container.friendship_service.override(providers.Object(friendship_mock))
    container.user_block_service.override(providers.Object(block_mock))
    container.friend_detail_service.override(providers.Object(detail_mock))

    app = FastAPI()
    app.container = container

    @app.middleware("http")
    async def inject_user(request, call_next):
        user_id = request.headers.get("X-User-Id")
        if user_id:
            request.state.user_id = user_id
        return await call_next(request)

    app.include_router(friend_router, prefix="/api")

    container.wire(modules=[
        "app.domain.friend.router.friendship",
        "app.domain.friend.router.user_block",
        "app.domain.friend.router.detail",
    ])

    try:
        with TestClient(app) as client:
            yield client, friendship_mock, block_mock, detail_mock
    finally:
        container.unwire()


def _friendship_dto(
    friendship_id: str = "FS_1",
    status: FriendshipStatus = FriendshipStatus.PENDING,
    peer_id: str = "USER_b",
) -> FriendshipData:
    return FriendshipData(
        friendship_id=friendship_id,
        status=status,
        peer=FriendPeerData(
            user_id=peer_id,
            user_name="피어",
            age=25,
            gender=Gender.MALE,
            nationality="KR",
        ),
        is_requester=True,
        created_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        updated_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
    )


# ──────────────────────────────────────────────────────────────────
# POST /api/friend/requests — 친구 요청
# ──────────────────────────────────────────────────────────────────

class TestSendFriendRequestEndpoint:
    def test_returns_201_with_payload_on_success(self, http):
        client, friendship_mock, _, _ = http
        friendship_mock.send_request.return_value = _friendship_dto()

        resp = client.post(
            "/api/friend/friendships/requests",
            json={"addressee_id": "USER_b"},
            headers={"X-User-Id": "USER_a"},
        )

        assert resp.status_code == 201
        body = resp.json()
        assert body["friendship_id"] == "FS_1"
        assert body["status"] == "pending"
        assert body["peer"]["user_id"] == "USER_b"
        assert body["is_requester"] is True

    def test_returns_400_on_value_error(self, http):
        client, friendship_mock, _, _ = http
        friendship_mock.send_request.side_effect = ValueError("이미 친구 요청을 보낸 상대입니다.")

        resp = client.post(
            "/api/friend/friendships/requests",
            json={"addressee_id": "USER_b"},
            headers={"X-User-Id": "USER_a"},
        )

        assert resp.status_code == 400
        assert resp.json()["detail"] == "이미 친구 요청을 보낸 상대입니다."

    def test_returns_422_on_missing_body(self, http):
        client, _, _, _ = http

        resp = client.post(
            "/api/friend/friendships/requests",
            json={},  # addressee_id 누락
            headers={"X-User-Id": "USER_a"},
        )

        assert resp.status_code == 422


# ──────────────────────────────────────────────────────────────────
# PATCH /api/friend/requests/{id}/accept — 수락
# ──────────────────────────────────────────────────────────────────

class TestAcceptEndpoint:
    def test_returns_200_with_message(self, http):
        client, friendship_mock, _, _ = http
        friendship_mock.accept_request.return_value = None

        resp = client.patch(
            "/api/friend/friendships/requests/FS_x/accept",
            headers={"X-User-Id": "USER_b"},
        )

        assert resp.status_code == 200
        assert resp.json() == {"message": "친구 요청을 수락했습니다."}

    def test_maps_value_error_to_400(self, http):
        client, friendship_mock, _, _ = http
        friendship_mock.accept_request.side_effect = ValueError("존재하지 않는 친구 요청입니다.")

        resp = client.patch(
            "/api/friend/friendships/requests/FS_x/accept",
            headers={"X-User-Id": "USER_b"},
        )

        assert resp.status_code == 400
        assert "존재하지 않는" in resp.json()["detail"]

    def test_maps_permission_error_to_403(self, http):
        client, friendship_mock, _, _ = http
        friendship_mock.accept_request.side_effect = PermissionError("요청 수락 권한이 없습니다.")

        resp = client.patch(
            "/api/friend/friendships/requests/FS_x/accept",
            headers={"X-User-Id": "USER_c"},
        )

        assert resp.status_code == 403


# ──────────────────────────────────────────────────────────────────
# GET /api/friend — 친구 목록
# ──────────────────────────────────────────────────────────────────

class TestGetFriendsEndpoint:
    def test_returns_list_with_cursor(self, http):
        client, friendship_mock, _, _ = http
        friendship_mock.get_friends.return_value = FriendshipListData(
            items=[_friendship_dto(status=FriendshipStatus.ACCEPTED)],
            next_cursor="FS_cursor",
        )

        resp = client.get("/api/friend/friendships", headers={"X-User-Id": "USER_a"})

        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        assert body["next_cursor"] == "FS_cursor"


# ──────────────────────────────────────────────────────────────────
# POST /api/friend/blocks — 차단
# ──────────────────────────────────────────────────────────────────

class TestBlockEndpoint:
    def test_returns_201_on_success(self, http):
        client, _, block_mock, _ = http
        block_mock.block_user.return_value = UserBlockData(
            block_id="BLK_1",
            blocked=FriendPeerData(
                user_id="USER_b",
                user_name="타겟",
                age=25,
                gender=Gender.MALE,
                nationality="KR",
            ),
            created_at=datetime(2026, 4, 20, tzinfo=timezone.utc),
        )

        resp = client.post(
            "/api/friend/blocks",
            json={"target_user_id": "USER_b"},
            headers={"X-User-Id": "USER_a"},
        )

        assert resp.status_code == 201
        assert resp.json()["block_id"] == "BLK_1"
        assert resp.json()["blocked"]["user_id"] == "USER_b"

    def test_returns_400_on_value_error(self, http):
        client, _, block_mock, _ = http
        block_mock.block_user.side_effect = ValueError("이미 차단한 유저입니다.")

        resp = client.post(
            "/api/friend/blocks",
            json={"target_user_id": "USER_b"},
            headers={"X-User-Id": "USER_a"},
        )

        assert resp.status_code == 400


# ──────────────────────────────────────────────────────────────────
# GET /api/friend/detail/{user_id} — 친구 상세 조회
# ──────────────────────────────────────────────────────────────────

def _friend_detail_dto(user_id: str = "USER_b") -> FriendDetailData:
    return FriendDetailData(
        user_id=user_id,
        user_name="피어",
        age=25,
        gender=Gender.MALE,
        nationality="KR",
        travel_styles=[TravelStyle.FOOD],
        friendship_id=None,
        friendship_status=None,
        is_requester=None,
        i_blocked_peer=False,
    )


class TestDetailEndpoint:
    def test_returns_200_with_public_profile(self, http):
        client, _, _, detail_mock = http
        detail_mock.get_friend_detail.return_value = _friend_detail_dto()

        resp = client.get(
            "/api/friend/detail/USER_b",
            headers={"X-User-Id": "USER_a"},
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["user_id"] == "USER_b"
        assert body["user_name"] == "피어"
        assert body["travel_styles"] == ["food"]
        # 민감 정보는 응답에 없어야 함
        assert "email" not in body
        assert "phone_number" not in body
        assert "auth_provider" not in body

    def test_returns_404_on_user_not_found(self, http):
        client, _, _, detail_mock = http
        detail_mock.get_friend_detail.side_effect = UserNotFoundError("존재하지 않는 유저입니다.")

        resp = client.get(
            "/api/friend/detail/USER_ghost",
            headers={"X-User-Id": "USER_a"},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "존재하지 않는 유저입니다."

    def test_returns_400_on_incomplete_profile(self, http):
        client, _, _, detail_mock = http
        detail_mock.get_friend_detail.side_effect = ValueError("2차 회원가입이 완료되지 않은 유저입니다.")

        resp = client.get(
            "/api/friend/detail/USER_b",
            headers={"X-User-Id": "USER_a"},
        )

        assert resp.status_code == 400
        assert "2차 회원가입" in resp.json()["detail"]
