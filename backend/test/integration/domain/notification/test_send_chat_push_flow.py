"""send_chat_push 가드 체인 + 만료 토큰 정리 통합.

Firebase SDK 만 stub — DB(가드/조회/정리) 는 실 PostgreSQL 로 검증한다.
가드 체인:
    (1) 방별 — `chat_room_member.notification_muted IS NOT TRUE AND is_left=false`
    (2) 전역 — `users.notification_muted IS NOT TRUE`
    (3) 토큰 보유 — 0건이면 multicast skip
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from firebase_admin import messaging

from app.database.session import UnitOfWork, mongodb
from app.domain.auth.model.user import User, UserStatus
from app.domain.chat.model.chat_room_member import ChatRoomMember
from app.domain.notification.repository.fcm_token import FcmTokenRepository
from app.domain.notification.service.fcm import FcmService
from test.integration.domain.notification.conftest import fetch_tokens_by_user


pytestmark = pytest.mark.integration


class TestHappyPath:
    async def test_message_push_revalidates_current_body_and_tombstone(
        self, fcm_service, seed_room_with_members, fcm_messaging_stub,
        mongo_db, monkeypatch,
    ):
        room_id, [user_a] = await seed_room_with_members(1)
        await fcm_service.register_token(user_id=user_a, token="tok-A")
        monkeypatch.setattr(mongodb, "database", mongo_db)
        collection = mongo_db["chat_message"]
        await collection.drop()
        await collection.insert_one({
            "_id": "M_push_revision",
            "chat_room_id": room_id,
            "content": "edited body",
            "deleted_at": None,
        })
        fcm_messaging_stub.set_responses([True])

        sent = await fcm_service.send_chat_push(
            user_ids=[user_a], chat_room_id=room_id, sender_id="SYS",
            title="t", body="original body", message_id="M_push_revision",
        )
        assert sent == 1
        assert fcm_messaging_stub.messages[-1].notification.body == "edited body"

        await collection.update_one(
            {"_id": "M_push_revision"}, {"$set": {"deleted_at": datetime.now(timezone.utc)}},
        )
        sent = await fcm_service.send_chat_push(
            user_ids=[user_a], chat_room_id=room_id, sender_id="SYS",
            title="t", body="original body", message_id="M_push_revision",
        )
        assert sent == 0
        assert len(fcm_messaging_stub.messages) == 1

    async def test_old_message_generation_does_not_push_after_leave_and_rejoin(
        self, fcm_service, session_factory, seed_room_with_members, fcm_messaging_stub,
    ):
        room_id, [user_id] = await seed_room_with_members(1)
        await fcm_service.register_token(user_id=user_id, token="tok-ABA")
        async with session_factory() as session:
            member = await session.get(ChatRoomMember, (room_id, user_id))
            old_generation = member.joined_at
            member.is_left = True
            await session.commit()
        async with session_factory() as session:
            member = await session.get(ChatRoomMember, (room_id, user_id))
            member.is_left = False
            member.joined_at = old_generation + timedelta(milliseconds=1)
            await session.commit()

        sent = await fcm_service.send_chat_push(
            user_ids=[user_id],
            expected_membership_generations={user_id: old_generation},
            chat_room_id=room_id,
            sender_id="SYS",
            title="old",
            body="pre-rejoin private body",
        )

        assert sent == 0
        assert fcm_messaging_stub.calls == []

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
    async def test_concurrent_invalid_token_cleanup_does_not_upgrade_share_locks(
        self, fcm_service, session_factory, seed_room_with_members, monkeypatch,
        fcm_messaging_stub,
    ):
        room_id, [user_a] = await seed_room_with_members(1)
        await fcm_service.register_token(user_id=user_a, token="dead-tok")
        both_started = asyncio.Event()
        release = asyncio.Event()
        started_count = 0

        async def blocked_invalid_batch(*_args, **_kwargs):
            nonlocal started_count
            started_count += 1
            if started_count == 2:
                both_started.set()
            await release.wait()
            return SimpleNamespace(responses=[SimpleNamespace(
                success=False,
                exception=messaging.UnregisteredError("unregistered"),
            )])

        monkeypatch.setattr(
            "app.domain.notification.service.fcm.asyncio.to_thread",
            blocked_invalid_batch,
        )
        other_service = FcmService(uow=UnitOfWork(session_factory))
        sends = [asyncio.create_task(service.send_chat_push(
            user_ids=[user_a], chat_room_id=room_id,
            sender_id="SYS", title="t", body="private",
        )) for service in (fcm_service, other_service)]
        await asyncio.wait_for(both_started.wait(), timeout=5)
        release.set()

        assert await asyncio.wait_for(asyncio.gather(*sends), timeout=5) == [0, 0]
        assert await fetch_tokens_by_user(session_factory, user_a) == []

    async def test_inactive_member_is_excluded(
        self, fcm_service, session_factory,
        seed_room_with_members, fcm_messaging_stub,
    ):
        room_id, [user_a, user_b] = await seed_room_with_members(2)
        await fcm_service.register_token(user_id=user_a, token="tok-A")
        await fcm_service.register_token(user_id=user_b, token="tok-B")
        async with session_factory() as session:
            target = await session.get(User, user_a)
            target.status = UserStatus.INACTIVE
            await session.commit()
        fcm_messaging_stub.set_responses([True])

        sent = await fcm_service.send_chat_push(
            user_ids=[user_a, user_b], chat_room_id=room_id,
            sender_id="SYS", title="t", body="private",
        )

        assert sent == 1
        assert fcm_messaging_stub.calls[0] == ["tok-B"]

    async def test_account_and_membership_revocation_wait_for_accepted_multicast(
        self, fcm_service, session_factory, seed_room_with_members,
        fcm_messaging_stub, monkeypatch,
    ):
        room_id, [user_a, user_c] = await seed_room_with_members(2)
        await fcm_service.register_token(user_id=user_a, token="tok-A")
        fcm_messaging_stub.set_responses([True])
        started = asyncio.Event()
        release = asyncio.Event()
        deactivate_reached = asyncio.Event()
        leave_reached = asyncio.Event()
        transfer_reached = asyncio.Event()

        async def blocked_to_thread(fn, *args, **kwargs):
            started.set()
            await release.wait()
            return fn(*args, **kwargs)

        monkeypatch.setattr(
            "app.domain.notification.service.fcm.asyncio.to_thread",
            blocked_to_thread,
        )
        send_task = asyncio.create_task(fcm_service.send_chat_push(
            user_ids=[user_a], chat_room_id=room_id,
            sender_id="SYS", title="t", body="private",
        ))
        await asyncio.wait_for(started.wait(), timeout=5)

        async def deactivate():
            async with session_factory() as session:
                deactivate_reached.set()
                target = await session.get(User, user_a, with_for_update=True)
                target.status = UserStatus.INACTIVE
                await session.commit()

        deactivate_task = asyncio.create_task(deactivate())

        original_upsert = FcmTokenRepository.upsert_by_token

        async def observed_upsert(repo, *, user_id, token):
            transfer_reached.set()
            return await original_upsert(repo, user_id=user_id, token=token)

        monkeypatch.setattr(FcmTokenRepository, "upsert_by_token", observed_upsert)
        transfer_service = FcmService(uow=UnitOfWork(session_factory))
        transfer_task = asyncio.create_task(transfer_service.register_token(
            user_id=user_c, token="tok-A",
        ))

        async def leave():
            async with session_factory() as session:
                leave_reached.set()
                member = await session.get(
                    ChatRoomMember, (room_id, user_a), with_for_update=True,
                )
                member.is_left = True
                await session.commit()

        leave_task = asyncio.create_task(leave())
        await asyncio.wait_for(asyncio.gather(
            deactivate_reached.wait(),
            leave_reached.wait(),
            transfer_reached.wait(),
        ), timeout=5)
        await asyncio.sleep(0)
        assert not deactivate_task.done()
        assert not leave_task.done()
        assert not transfer_task.done()

        release.set()
        assert await asyncio.wait_for(send_task, timeout=5) == 1
        await asyncio.wait_for(deactivate_task, timeout=5)
        await asyncio.wait_for(leave_task, timeout=5)
        await asyncio.wait_for(transfer_task, timeout=5)
        assert {row.token for row in await fetch_tokens_by_user(
            session_factory, user_c,
        )} == {"tok-A"}

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
        await fcm_service.register_token(user_id=user_a, token="tok-A2")
        await fcm_service.register_token(user_id=user_b, token="tok-B1")

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
        assert len(rows) == 1
