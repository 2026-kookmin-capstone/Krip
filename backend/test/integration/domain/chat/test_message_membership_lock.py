import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.domain.chat.model.chat_room import ChatRoom, ChatRoomType
from app.domain.chat.model.chat_room_member import ChatRoomMember
from app.domain.chat.repository.chat_member import ChatRoomMemberRepository


pytestmark = pytest.mark.integration


async def test_send_membership_lock_blocks_concurrent_leave_update(
    seed_users, session_factory,
):
    user_id, _, _ = await seed_users(3)
    async with session_factory() as session:
        room = ChatRoom(type=ChatRoomType.GROUP, title="lock", creator_id=user_id)
        session.add(room)
        await session.flush()
        room_id = str(room.chat_room_id)
        session.add(ChatRoomMember(chat_room_id=room_id, user_id=user_id))
        await session.commit()

    async with session_factory() as send_session:
        assert await ChatRoomMemberRepository(send_session).is_active_member_for_share(
            room_id, user_id,
        )

        async with session_factory() as leave_session:
            probe = (
                select(ChatRoomMember)
                .where(
                    ChatRoomMember.chat_room_id == room_id,
                    ChatRoomMember.user_id == user_id,
                )
                .with_for_update(nowait=True)
            )
            with pytest.raises(DBAPIError):
                await leave_session.execute(probe)
