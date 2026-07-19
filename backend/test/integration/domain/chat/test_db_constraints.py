"""채팅 도메인 DB 제약 통합 테스트.

실제 PostgreSQL 을 대상으로 CHECK / UNIQUE / SET NULL / GENERATED 컬럼의 동작을 검증.
`POSTGRES_TEST_URL` 미설정 환경에선 `conftest.py` 가 모듈 단위 skip.
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from app.domain.chat.model.chat_room import ChatRoom, ChatRoomType
from app.domain.chat.model.chat_room_member import ChatRoomMember


pytestmark = pytest.mark.integration


class TestUniqueDirectPair:
    async def test_duplicate_pair_raises_integrity_error(
        self, session_factory, seed_users,
    ):
        a, b, _ = await seed_users(3)

        async with session_factory() as s:
            s.add(
                ChatRoom(
                    chat_room_id="CR_1",
                    type=ChatRoomType.DIRECT,
                    creator_id=a,
                    direct_user_a_id=a,
                    direct_user_b_id=b,
                )
            )
            await s.commit()

        with pytest.raises(IntegrityError):
            async with session_factory() as s:
                s.add(
                    ChatRoom(
                        chat_room_id="CR_2",
                        type=ChatRoomType.DIRECT,
                        creator_id=a,
                        direct_user_a_id=a,
                        direct_user_b_id=b,
                    )
                )
                await s.commit()

    async def test_group_rooms_allow_duplicate_null_pairs(
        self, session_factory, seed_users,
    ):
        """GROUP 방은 direct_user_* 가 NULL 이므로 UNIQUE partial index(WHERE type='DIRECT')
        에 영향받지 않아 여러 개 존재 가능."""
        (a,) = await seed_users(1)

        async with session_factory() as s:
            s.add_all([
                ChatRoom(chat_room_id="CR_g1", type=ChatRoomType.GROUP, creator_id=a),
                ChatRoom(chat_room_id="CR_g2", type=ChatRoomType.GROUP, creator_id=a),
            ])
            await s.commit()

        async with session_factory() as s:
            rows = (await s.execute(
                select(ChatRoom).where(ChatRoom.type == ChatRoomType.GROUP)
            )).scalars().all()
            assert len(rows) == 2


class TestCheckConstraint:
    async def test_direct_requires_canonical_order(
        self, session_factory, seed_users,
    ):
        """direct_user_a_id >= direct_user_b_id 면 CHECK 위반."""
        a, b, _ = await seed_users(3)

        low, high = sorted([a, b])

        with pytest.raises(IntegrityError):
            async with session_factory() as s:
                s.add(
                    ChatRoom(
                        chat_room_id="CR_bad",
                        type=ChatRoomType.DIRECT,
                        creator_id=a,
                        direct_user_a_id=high,
                        direct_user_b_id=low,
                    )
                )
                await s.commit()

    async def test_group_with_direct_users_violates_check(
        self, session_factory, seed_users,
    ):
        """GROUP 방인데 direct_user_* 가 채워져 있으면 CHECK 위반."""
        a, b, _ = await seed_users(3)

        with pytest.raises(IntegrityError):
            async with session_factory() as s:
                s.add(
                    ChatRoom(
                        chat_room_id="CR_bad",
                        type=ChatRoomType.GROUP,
                        creator_id=a,
                        direct_user_a_id=a,
                        direct_user_b_id=b,
                    )
                )
                await s.commit()

    async def test_direct_allows_null_after_withdrawal(
        self, session_factory, seed_users,
    ):
        """탈퇴 정책: DIRECT 방에서 한 쪽이 NULL 이 되어도 CHECK 통과해야 한다."""
        a, b, _ = await seed_users(3)
        low, high = sorted([a, b])

        async with session_factory() as s:
            s.add(
                ChatRoom(
                    chat_room_id="CR_dir",
                    type=ChatRoomType.DIRECT,
                    creator_id=low,
                    direct_user_a_id=low,
                    direct_user_b_id=high,
                )
            )
            await s.commit()

        async with session_factory() as s:
            await s.execute(
                update(ChatRoom)
                .where(ChatRoom.chat_room_id == "CR_dir")
                .values(direct_user_a_id=None)
            )
            await s.commit()

        async with session_factory() as s:
            row = (await s.execute(select(ChatRoom).where(ChatRoom.chat_room_id == "CR_dir"))).scalar_one()
            assert row.direct_user_a_id is None
            assert row.direct_user_b_id == high


class TestOnDeleteSetNull:
    async def test_user_deletion_preserves_room(
        self, session_factory, seed_users, engine,
    ):
        a, b, _ = await seed_users(3)
        low, high = sorted([a, b])

        async with session_factory() as s:
            s.add(
                ChatRoom(
                    chat_room_id="CR_dir",
                    type=ChatRoomType.DIRECT,
                    creator_id=low,
                    direct_user_a_id=low,
                    direct_user_b_id=high,
                )
            )
            await s.commit()

        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM users WHERE user_id = :uid"), {"uid": low})

        async with session_factory() as s:
            row = (await s.execute(
                select(ChatRoom).where(ChatRoom.chat_room_id == "CR_dir")
            )).scalar_one()
            assert row.direct_user_a_id is None
            assert row.direct_user_b_id == high
            assert row.creator_id is None


class TestGeneratedColumn:
    async def test_effective_last_at_uses_created_at_when_no_message(
        self, session_factory, seed_users,
    ):
        a, b, _ = await seed_users(3)
        low, high = sorted([a, b])

        async with session_factory() as s:
            s.add(
                ChatRoom(
                    chat_room_id="CR_new",
                    type=ChatRoomType.DIRECT,
                    creator_id=low,
                    direct_user_a_id=low,
                    direct_user_b_id=high,
                )
            )
            await s.commit()

        async with session_factory() as s:
            row = (await s.execute(
                select(ChatRoom).where(ChatRoom.chat_room_id == "CR_new")
            )).scalar_one()
            assert row.last_message_at is None
            assert row.effective_last_at == row.created_at

    async def test_effective_last_at_uses_last_message_at_when_present(
        self, session_factory, seed_users,
    ):
        a, b, _ = await seed_users(3)
        low, high = sorted([a, b])

        ref_time = datetime(2030, 1, 1, tzinfo=timezone.utc)
        async with session_factory() as s:
            s.add(
                ChatRoom(
                    chat_room_id="CR_active",
                    type=ChatRoomType.DIRECT,
                    creator_id=low,
                    direct_user_a_id=low,
                    direct_user_b_id=high,
                    last_message_at=ref_time,
                    last_message_id="MSG_x",
                    last_message_server_seq=1,
                )
            )
            await s.commit()

        async with session_factory() as s:
            row = (await s.execute(
                select(ChatRoom).where(ChatRoom.chat_room_id == "CR_active")
            )).scalar_one()
            assert row.effective_last_at == ref_time


class TestMemberActiveIndex:
    async def test_find_user_room_ids_excludes_is_left(
        self, session_factory, seed_users,
    ):
        from app.domain.chat.repository.chat_member import ChatRoomMemberRepository

        a, b, _ = await seed_users(3)
        low, high = sorted([a, b])

        async with session_factory() as s:
            s.add_all([
                ChatRoom(
                    chat_room_id="CR_active",
                    type=ChatRoomType.DIRECT,
                    creator_id=low,
                    direct_user_a_id=low,
                    direct_user_b_id=high,
                ),
                ChatRoom(
                    chat_room_id="CR_left",
                    type=ChatRoomType.GROUP,
                    creator_id=low,
                ),
            ])
            s.add_all([
                ChatRoomMember(chat_room_id="CR_active", user_id=low, is_left=False),
                ChatRoomMember(chat_room_id="CR_left", user_id=low, is_left=True),
            ])
            await s.commit()

        async with session_factory() as s:
            repo = ChatRoomMemberRepository(s)
            ids = await repo.find_user_room_ids(low)
            assert ids == ["CR_active"]
