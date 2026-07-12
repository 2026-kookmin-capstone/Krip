"""send_chat_push 가드 체인 + 만료 토큰 정리 통합.

Firebase SDK 만 stub — DB(가드/조회/정리) 는 실 PostgreSQL 로 검증한다.
가드 체인:
    (1) 방별 — `chat_room_member.notification_muted IS NOT TRUE AND is_left=false`
    (2) 전역 — `users.notification_muted IS NOT TRUE`
    (3) 토큰 보유 — 0건이면 multicast skip
"""
import pytest
from firebase_admin import messaging

from test.integration.domain.notification.conftest import fetch_tokens_by_user


pytestmark = pytest.mark.integration


class TestHappyPath:
    async def test_all_pushable_users_get_multicast(
        self,
        fcm_service,
        seed_room_with_members,
        fcm_messaging_stub,
    ):
        """방 멤버 2명 모두 토큰 등록 + mute 없음 → multicast 1회, success_count = 토큰 합."""
        room_id, [user_a, user_b] = await seed_room_with_members(2)
        await fcm_service.register_token(user_id=user_a, token="tok-A1")
        await fcm_service.register_token(user_id=user_a, token="tok-A2")
        await fcm_service.register_token(user_id=user_b, token="tok-B1")
        fcm_messaging_stub.set_responses([True, True, True])

        sent = await fcm_service.send_chat_push(
            user_ids=[user_a, user_b],
            chat_room_id=room_id,
            sender_id="SYS",
            title="새 메시지",
            body="hi",
        )

        assert sent == 3
        assert len(fcm_messaging_stub.calls) == 1
        assert set(fcm_messaging_stub.calls[0]) == {"tok-A1", "tok-A2", "tok-B1"}

    async def test_empty_user_ids_skips_multicast(
        self, fcm_service, fcm_messaging_stub,
    ):
        """수신 후보 0명 — DB 쿼리도 multicast 호출도 발생하지 않음."""
        sent = await fcm_service.send_chat_push(
            user_ids=[],
            chat_room_id="CR_x", sender_id="SYS",
            title="t", body="b",
        )
        assert sent == 0
        assert fcm_messaging_stub.calls == []


class TestRoomMuteGuard:
    async def test_room_muted_user_excluded(
        self, fcm_service, mute_service,
        seed_room_with_members, fcm_messaging_stub,
    ):
        """방별 mute=True 인 user 는 multicast 토큰 목록에서 제외."""
        room_id, [user_a, user_b] = await seed_room_with_members(2)
        await fcm_service.register_token(user_id=user_a, token="tok-A")
        await fcm_service.register_token(user_id=user_b, token="tok-B")

        await mute_service.set_room_mute(
            user_id=user_a, chat_room_id=room_id, muted=True,
        )
        fcm_messaging_stub.set_responses([True])

        sent = await fcm_service.send_chat_push(
            user_ids=[user_a, user_b],
            chat_room_id=room_id, sender_id="SYS",
            title="t", body="b",
        )

        assert sent == 1
        assert fcm_messaging_stub.calls[0] == ["tok-B"]

    async def test_left_member_excluded(
        self, fcm_service, session_factory,
        seed_room_with_members, fcm_messaging_stub,
    ):
        """`is_left=True` 인 멤버는 mute 와 무관하게 푸시 차단 — 탈퇴자 누수 방어."""
        room_id, [user_a, user_b] = await seed_room_with_members(2)
        await fcm_service.register_token(user_id=user_a, token="tok-A")
        await fcm_service.register_token(user_id=user_b, token="tok-B")

        async with session_factory() as session:
            from app.domain.chat.model.chat_room_member import ChatRoomMember
            member = await session.get(ChatRoomMember, (room_id, user_a))
            member.is_left = True
            await session.commit()

        fcm_messaging_stub.set_responses([True])

        sent = await fcm_service.send_chat_push(
            user_ids=[user_a, user_b],
            chat_room_id=room_id, sender_id="SYS",
            title="t", body="b",
        )

        assert sent == 1
        assert fcm_messaging_stub.calls[0] == ["tok-B"]


class TestGlobalMuteGuard:
    async def test_globally_muted_user_excluded(
        self, fcm_service, mute_service,
        seed_room_with_members, fcm_messaging_stub,
    ):
        """전역 mute=True 인 user 는 어느 방의 푸시든 제외."""
        room_id, [user_a, user_b] = await seed_room_with_members(2)
        await fcm_service.register_token(user_id=user_a, token="tok-A")
        await fcm_service.register_token(user_id=user_b, token="tok-B")

        await mute_service.set_global_mute(user_id=user_a, muted=True)
        fcm_messaging_stub.set_responses([True])

        sent = await fcm_service.send_chat_push(
            user_ids=[user_a, user_b],
            chat_room_id=room_id, sender_id="SYS",
            title="t", body="b",
        )

        assert sent == 1
        assert fcm_messaging_stub.calls[0] == ["tok-B"]

    async def test_all_muted_returns_zero_without_multicast(
        self, fcm_service, mute_service,
        seed_room_with_members, fcm_messaging_stub,
    ):
        """모두 차단된 케이스 — multicast 호출 자체가 일어나지 않음 (FCM 비용 0)."""
        room_id, [user_a, user_b] = await seed_room_with_members(2)
        await fcm_service.register_token(user_id=user_a, token="tok-A")
        await fcm_service.register_token(user_id=user_b, token="tok-B")
        await mute_service.set_global_mute(user_id=user_a, muted=True)
        await mute_service.set_global_mute(user_id=user_b, muted=True)

        sent = await fcm_service.send_chat_push(
            user_ids=[user_a, user_b],
            chat_room_id=room_id, sender_id="SYS",
            title="t", body="b",
        )

        assert sent == 0
        assert fcm_messaging_stub.calls == []


class TestTokenGuard:
    async def test_no_tokens_skips_multicast(
        self, fcm_service, seed_room_with_members, fcm_messaging_stub,
    ):
        """가드 (1)(2) 통과해도 토큰 0건이면 multicast skip."""
        room_id, [user_a, user_b] = await seed_room_with_members(2)

        sent = await fcm_service.send_chat_push(
            user_ids=[user_a, user_b],
            chat_room_id=room_id, sender_id="SYS",
            title="t", body="b",
        )

        assert sent == 0
        assert fcm_messaging_stub.calls == []


class TestUnregisteredTokenCleanup:
    async def test_unregistered_tokens_are_deleted(
        self,
        fcm_service,
        session_factory,
        seed_room_with_members,
        fcm_messaging_stub,
    ):
        """`UnregisteredError` (앱 삭제) 응답인 토큰은 같은 트랜잭션에서 bulk DELETE."""
        room_id, [user_a, user_b] = await seed_room_with_members(2)
        await fcm_service.register_token(user_id=user_a, token="tok-A1")
        await fcm_service.register_token(user_id=user_a, token="tok-A2")  # 이게 만료
        await fcm_service.register_token(user_id=user_b, token="tok-B1")

        # stub 응답은 조회 순서의 두 번째 토큰만 만료 처리한다.
        fcm_messaging_stub.set_responses(
            success=[True, False, True],
            errors=[None, messaging.UnregisteredError("expired"), None],
        )

        sent = await fcm_service.send_chat_push(
            user_ids=[user_a, user_b],
            chat_room_id=room_id, sender_id="SYS",
            title="t", body="b",
        )

        called_tokens = fcm_messaging_stub.calls[0]
        invalid_token = called_tokens[1]
        a_rows = await fetch_tokens_by_user(session_factory, user_a)
        b_rows = await fetch_tokens_by_user(session_factory, user_b)
        all_remaining = {r.token for r in a_rows + b_rows}
        assert invalid_token not in all_remaining
        assert sent == 2

    async def test_firebase_error_does_not_delete_tokens(
        self,
        fcm_service,
        session_factory,
        seed_room_with_members,
        fcm_messaging_stub,
        monkeypatch,
    ):
        """글로벌 FirebaseError(인증/네트워크) 는 토큰 정리 없이 0 반환 — 일시 장애와
        앱 삭제(UnregisteredError) 는 다르게 다뤄야 함."""
        from firebase_admin.exceptions import FirebaseError

        room_id, [user_a, _] = await seed_room_with_members(2)
        await fcm_service.register_token(user_id=user_a, token="tok-A")

        def _raise(*args, **kwargs):
            raise FirebaseError(code="UNAVAILABLE", message="boom")

        monkeypatch.setattr(
            "app.domain.notification.service.fcm.messaging.send_each_for_multicast",
            _raise,
        )

        sent = await fcm_service.send_chat_push(
            user_ids=[user_a],
            chat_room_id=room_id, sender_id="SYS",
            title="t", body="b",
        )

        assert sent == 0
        rows = await fetch_tokens_by_user(session_factory, user_a)
        assert len(rows) == 1  # 토큰 보존 — 일시 장애로 정리 안 함
