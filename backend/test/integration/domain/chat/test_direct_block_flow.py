"""1:1 방 차단 상태와 송신 권한의 end-to-end 통합.

송신 권한은 RDB 를 pair advisory lock 으로 판정한다 — Redis 캐시 없이
block/unblock 이 즉시 다음 송신에 반영되는지 검증.
"""
import pytest

from app.domain.chat.model.chat_message import MessageType
from app.domain.chat.service.room import RoomService
from app.domain.friend.service.user_block import UserBlockService


pytestmark = pytest.mark.integration


class TestDirectBlockSendFlow:
    async def test_block_rejects_next_direct_send(
        self, uow, seed_users, chat_fanout_stub, message_service,
        patch_external_clients,
    ):
        """차단 즉시 다음 송신 거절 (TTL 대기 없음)."""
        a, b, _ = await seed_users(3)

        room_svc = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await room_svc.create_direct_room(me_id=a, peer_user_id=b)
        room_id = room.chat_room_id

        block_service = UserBlockService(uow=uow)
        await block_service.block_user(user_id=a, target_user_id=b)

        with pytest.raises(PermissionError, match="차단"):
            await message_service.send_message(
                sender_user_id=a, sender_session_id="WS_A", room_id=room_id,
                client_msg_id="cm-2", msg_type=MessageType.TEXT, content="blocked",
            )

    async def test_unblock_allows_immediate_next_send(
        self, uow, seed_users, chat_fanout_stub, message_service,
        patch_external_clients,
    ):
        """차단 → 해제 즉시 송신 가능 (TTL 대기 없음)."""
        a, b, _ = await seed_users(3)

        room_svc = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await room_svc.create_direct_room(me_id=a, peer_user_id=b)
        room_id = room.chat_room_id

        block_service = UserBlockService(uow=uow)

        await block_service.block_user(user_id=a, target_user_id=b)
        with pytest.raises(PermissionError):
            await message_service.send_message(
                sender_user_id=a, sender_session_id="WS_A", room_id=room_id,
                client_msg_id="cm-a1", msg_type=MessageType.TEXT, content="x",
            )

        await block_service.unblock_user(user_id=a, target_user_id=b)

        ack = await message_service.send_message(
            sender_user_id=a, sender_session_id="WS_A", room_id=room_id,
            client_msg_id="cm-a2", msg_type=MessageType.TEXT, content="restored",
        )
        assert ack.server_seq > 0

    async def test_peer_blocking_sender_also_rejects(
        self, uow, seed_users, chat_fanout_stub, message_service,
        patch_external_clients,
    ):
        """상대가 나를 차단했어도 내 송신은 거절 (양방향 체크)."""
        a, b, _ = await seed_users(3)
        room_svc = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await room_svc.create_direct_room(me_id=a, peer_user_id=b)

        # b 가 a 를 차단 — 그런데 room 은 이미 생성된 상태 (기존 채팅방 유지 정책)
        block_service = UserBlockService(uow=uow)
        await block_service.block_user(user_id=b, target_user_id=a)

        with pytest.raises(PermissionError, match="차단"):
            await message_service.send_message(
                sender_user_id=a, sender_session_id="WS_A", room_id=room.chat_room_id,
                client_msg_id="cm-peer-1", msg_type=MessageType.TEXT, content="nope",
            )

    async def test_group_room_unaffected_by_block(
        self, uow, seed_users, chat_fanout_stub, message_service,
        patch_external_clients, session_factory,
    ):
        """그룹 방은 차단 관계와 무관 — 같은 방에 있으면 메시지는 계속 전달."""
        from app.domain.friend.model.friendship import Friendship, FriendshipStatus

        a, b, _ = await seed_users(3)
        async with session_factory() as s:
            s.add(Friendship(
                requester_id=a, addressee_id=b, status=FriendshipStatus.ACCEPTED,
            ))
            await s.commit()

        room_svc = RoomService(
            uow=uow, fanout_service=chat_fanout_stub, message_service=message_service,
        )
        room = await room_svc.create_group_room(me_id=a, title="T", member_ids=[b])

        # 이미 그룹 방에 있는 상태에서 a 가 b 를 차단해도 그룹 송신은 유지
        # (차단은 friendship 을 삭제하지만 그룹 방 멤버십은 그대로)
        block_service = UserBlockService(uow=uow)
        await block_service.block_user(user_id=a, target_user_id=b)

        ack = await message_service.send_message(
            sender_user_id=a, sender_session_id="WS_A", room_id=room.chat_room_id,
            client_msg_id="cm-g-1", msg_type=MessageType.TEXT, content="group msg",
        )
        assert ack.server_seq > 0
