"""FcmService 토큰 등록/해제 통합 — 분기 + UNIQUE/CASCADE 까지 실 DB 검증.

핵심:
    - 신규 INSERT
    - 동일 (user, token) 재등록 → no-op
    - 동일 token 다른 user → owner 만 교체 (디바이스 계정 전환)
    - 해제 idempotent (없거나 타인 소유는 조용히 종료)
    - user CASCADE 로 토큰 자동 정리 (회원 탈퇴 영구 삭제 시)
"""
import asyncio

import pytest
from sqlalchemy import delete, text

from app.database.session import UnitOfWork
from app.domain.auth.model.user import User, UserStatus
from app.domain.notification.repository.fcm_token import FcmTokenRepository
from app.domain.notification.service.fcm import MAX_TOKENS_PER_USER, FcmService
from test.integration.domain.notification.conftest import fetch_tokens_by_user


pytestmark = pytest.mark.integration


async def wait_until_advisory_blocked(session_factory) -> None:
    async with session_factory() as session:
        while True:
            result = await session.execute(text(
                "SELECT EXISTS (SELECT 1 FROM pg_stat_activity "
                "WHERE datname = current_database() "
                "AND wait_event = 'advisory')"
            ))
            if result.scalar_one():
                return
            await asyncio.sleep(0)


class TestRegisterTokenFlow:
    async def test_inactive_user_cannot_take_active_users_token(
        self, fcm_service, session_factory, seed_users,
    ):
        [user_a, user_b] = await seed_users(2)
        await fcm_service.register_token(user_id=user_a, token="tok-shared")
        async with session_factory() as session:
            user = await session.get(User, user_b, with_for_update=True)
            user.status = UserStatus.INACTIVE
            await session.commit()

        with pytest.raises(PermissionError):
            await fcm_service.register_token(user_id=user_b, token="tok-shared")

        assert {row.token for row in await fetch_tokens_by_user(
            session_factory, user_a,
        )} == {"tok-shared"}
        assert await fetch_tokens_by_user(session_factory, user_b) == []

    async def test_registration_account_lock_serializes_with_deactivation(
        self, fcm_service, session_factory, seed_users, monkeypatch,
    ):
        [user_id] = await seed_users(1)
        registration_reached = asyncio.Event()
        release_registration = asyncio.Event()
        deactivation_reached = asyncio.Event()
        original_upsert = FcmTokenRepository.upsert_by_token

        async def blocked_upsert(repo, *, user_id, token):
            registration_reached.set()
            await release_registration.wait()
            return await original_upsert(repo, user_id=user_id, token=token)

        monkeypatch.setattr(FcmTokenRepository, "upsert_by_token", blocked_upsert)
        registration = asyncio.create_task(fcm_service.register_token(
            user_id=user_id, token="tok-A",
        ))
        await asyncio.wait_for(registration_reached.wait(), timeout=5)

        async def deactivate():
            async with session_factory() as session:
                deactivation_reached.set()
                user = await session.get(User, user_id, with_for_update=True)
                user.status = UserStatus.INACTIVE
                await session.commit()

        deactivation = asyncio.create_task(deactivate())
        await asyncio.wait_for(deactivation_reached.wait(), timeout=5)
        await asyncio.sleep(0)
        assert not deactivation.done()

        release_registration.set()
        await asyncio.wait_for(registration, timeout=5)
        await asyncio.wait_for(deactivation, timeout=5)

    async def test_new_token_is_inserted(
        self, fcm_service, session_factory, seed_users,
    ):
        [user_id] = await seed_users(1)

        result = await fcm_service.register_token(user_id=user_id, token="tok-A")

        rows = await fetch_tokens_by_user(session_factory, user_id)
        assert len(rows) == 1
        assert rows[0].token == "tok-A"
        assert result.fcm_token_id == rows[0].fcm_token_id

    async def test_same_user_same_token_is_noop(
        self, fcm_service, session_factory, seed_users,
    ):
        [user_id] = await seed_users(1)

        first = await fcm_service.register_token(user_id=user_id, token="tok-A")
        second = await fcm_service.register_token(user_id=user_id, token="tok-A")

        rows = await fetch_tokens_by_user(session_factory, user_id)
        assert len(rows) == 1
        assert first.fcm_token_id == second.fcm_token_id

    async def test_different_user_same_token_swaps_owner(
        self, fcm_service, session_factory, seed_users,
    ):
        """디바이스 계정 전환 케이스 — 같은 토큰이 다른 user 로 재등록되면 owner 만 교체."""
        [user_a, user_b] = await seed_users(2)

        await fcm_service.register_token(user_id=user_a, token="tok-shared")
        await fcm_service.register_token(user_id=user_b, token="tok-shared")

        a_rows = await fetch_tokens_by_user(session_factory, user_a)
        b_rows = await fetch_tokens_by_user(session_factory, user_b)
        assert a_rows == []
        assert len(b_rows) == 1
        assert b_rows[0].token == "tok-shared"

    async def test_concurrent_registration_is_serialized_and_keeps_exact_cap(
        self, fcm_service, session_factory, seed_users, monkeypatch,
    ):
        [user_id] = await seed_users(1)
        for index in range(MAX_TOKENS_PER_USER):
            await fcm_service.register_token(
                user_id=user_id, token=f"tok-seed-{index}",
            )

        first_reached = asyncio.Event()
        release_first = asyncio.Event()
        second_reached = asyncio.Event()
        original_upsert = FcmTokenRepository.upsert_by_token
        calls = 0

        async def observed_upsert(repo, *, user_id, token):
            nonlocal calls
            calls += 1
            if calls == 1:
                first_reached.set()
                await release_first.wait()
            else:
                second_reached.set()
            return await original_upsert(repo, user_id=user_id, token=token)

        monkeypatch.setattr(FcmTokenRepository, "upsert_by_token", observed_upsert)
        first_service = FcmService(UnitOfWork(session_factory))
        second_service = FcmService(UnitOfWork(session_factory))
        first = asyncio.create_task(first_service.register_token(
            user_id=user_id, token="tok-concurrent-A",
        ))
        await asyncio.wait_for(first_reached.wait(), timeout=5)
        second = asyncio.create_task(second_service.register_token(
            user_id=user_id, token="tok-concurrent-B",
        ))

        try:
            await asyncio.wait_for(
                wait_until_advisory_blocked(session_factory), timeout=5,
            )
            assert not second_reached.is_set()
        finally:
            release_first.set()
            await asyncio.wait_for(asyncio.gather(first, second), timeout=5)

        rows = await fetch_tokens_by_user(session_factory, user_id)
        assert len(rows) == MAX_TOKENS_PER_USER
        assert {"tok-concurrent-A", "tok-concurrent-B"} <= {
            row.token for row in rows
        }

    async def test_reciprocal_cross_user_transfers_are_globally_serialized(
        self, fcm_service, session_factory, seed_users, monkeypatch,
    ):
        user_a, user_b = await seed_users(2)
        for index in range(MAX_TOKENS_PER_USER):
            await fcm_service.register_token(
                user_id=user_a, token=f"tok-a-{index}",
            )
            await fcm_service.register_token(
                user_id=user_b, token=f"tok-b-{index}",
            )

        first_reached = asyncio.Event()
        release_first = asyncio.Event()
        second_reached = asyncio.Event()
        original_upsert = FcmTokenRepository.upsert_by_token
        calls = 0

        async def observed_upsert(repo, *, user_id, token):
            nonlocal calls
            calls += 1
            if calls == 1:
                first_reached.set()
                await release_first.wait()
            else:
                second_reached.set()
            return await original_upsert(repo, user_id=user_id, token=token)

        monkeypatch.setattr(FcmTokenRepository, "upsert_by_token", observed_upsert)
        first_service = FcmService(UnitOfWork(session_factory))
        second_service = FcmService(UnitOfWork(session_factory))
        first = asyncio.create_task(first_service.register_token(
            user_id=user_a, token="tok-b-0",
        ))
        await asyncio.wait_for(first_reached.wait(), timeout=5)
        second = asyncio.create_task(second_service.register_token(
            user_id=user_b, token="tok-a-0",
        ))

        try:
            await asyncio.wait_for(
                wait_until_advisory_blocked(session_factory), timeout=5,
            )
            assert not second_reached.is_set()
        finally:
            release_first.set()
            await asyncio.wait_for(asyncio.gather(first, second), timeout=5)

        a_rows = await fetch_tokens_by_user(session_factory, user_a)
        b_rows = await fetch_tokens_by_user(session_factory, user_b)
        assert len(a_rows) == MAX_TOKENS_PER_USER
        assert len(b_rows) == MAX_TOKENS_PER_USER
        assert "tok-b-0" in {row.token for row in a_rows}
        assert "tok-a-0" in {row.token for row in b_rows}

    async def test_one_user_can_register_multiple_tokens(
        self, fcm_service, session_factory, seed_users,
    ):
        """한 유저가 여러 디바이스 보유 가능 — UNIQUE 는 token 컬럼만."""
        [user_id] = await seed_users(1)

        await fcm_service.register_token(user_id=user_id, token="tok-1")
        await fcm_service.register_token(user_id=user_id, token="tok-2")

        rows = await fetch_tokens_by_user(session_factory, user_id)
        assert len(rows) == 2
        assert {r.token for r in rows} == {"tok-1", "tok-2"}


class TestUnregisterTokenFlow:
    async def test_owner_can_delete(
        self, fcm_service, session_factory, seed_users,
    ):
        [user_id] = await seed_users(1)
        await fcm_service.register_token(user_id=user_id, token="tok-A")

        await fcm_service.unregister_token(user_id=user_id, token="tok-A")

        rows = await fetch_tokens_by_user(session_factory, user_id)
        assert rows == []

    async def test_non_owner_silent_noop(
        self, fcm_service, session_factory, seed_users,
    ):
        """타인 토큰 해제 시도는 정보 누출 차단을 위해 조용히 종료 — 실 row 는 보존."""
        [user_a, user_b] = await seed_users(2)
        await fcm_service.register_token(user_id=user_a, token="tok-A")

        await fcm_service.unregister_token(user_id=user_b, token="tok-A")

        rows = await fetch_tokens_by_user(session_factory, user_a)
        assert len(rows) == 1

    async def test_nonexistent_token_silent_noop(
        self, fcm_service, seed_users,
    ):
        [user_id] = await seed_users(1)
        await fcm_service.unregister_token(user_id=user_id, token="never-existed")


class TestFcmTokenCascade:
    async def test_user_delete_cascades_tokens(
        self, fcm_service, session_factory, seed_users,
    ):
        """`fcm_token.user_id` FK 가 `ondelete=CASCADE` — user 삭제 시 토큰 자동 제거.

        회원 탈퇴 영구 삭제 흐름이 별도 토큰 정리 로직 없이 작동하는 근거.
        """
        [user_id] = await seed_users(1)
        await fcm_service.register_token(user_id=user_id, token="tok-1")
        await fcm_service.register_token(user_id=user_id, token="tok-2")

        async with session_factory() as session:
            await session.execute(delete(User).where(User.user_id == user_id))
            await session.commit()

        rows = await fetch_tokens_by_user(session_factory, user_id)
        assert rows == []
