"""RoomService 단위 테스트 — 그룹 방 생성 / 초대 / 퇴장 / 강퇴 (PHASE_2 #1).

공통 컨벤션은 `test_room_service.py` / `conftest.py` 참고 — 같은 fixture 재사용.
여기서는 Phase 2 에서 추가된 4 메서드의 성공/실패 분기만 다룬다.
"""
from types import SimpleNamespace

import pytest

from app.core.chat.redis_key import unread_key
from app.domain.chat.model.chat_room import ChatRoomType
from app.domain.chat.service.exception import ChatRoomNotFoundError
from app.domain.chat.service.room import RoomService
from test.unit.domain.chat.room_service.model_factory import ChatRoomFactory


@pytest.mark.unit
class TestCreateGroupRoom:
    async def test_service_rejects_more_than_100_members_after_dedup(
        self, service, friendship_repo_mock, chat_room_repo_mock,
    ):
        targets = {f"U_{index}" for index in range(100)}
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = targets

        with pytest.raises(ValueError, match="최대 100명"):
            await service.create_group_room(
                me_id="U_A", title="limit", member_ids=list(targets),
            )

        chat_room_repo_mock.save.assert_not_awaited()

    async def test_raises_when_only_self_after_dedup(self, service):
        with pytest.raises(ValueError, match="초대할 대상이 없습니다"):
            await service.create_group_room(
                me_id="U_A", title="캡스톤", member_ids=["U_A", "U_A"],
            )

    async def test_raises_when_any_target_not_friend(
        self, service, friendship_repo_mock,
    ):
        # U_B 만 친구, U_C 는 친구 아님
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B"}
        with pytest.raises(ValueError, match="친구가 아닌"):
            await service.create_group_room(
                me_id="U_A", title="T", member_ids=["U_B", "U_C"],
            )

    async def test_creates_room_with_creator_plus_members(
        self, service, friendship_repo_mock,
        chat_room_repo_mock, chat_member_repo_mock, fanout_mock,
    ):
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B", "U_C"}

        async def _save(room):
            room.chat_room_id = "CR_group"
            return room
        chat_room_repo_mock.save.side_effect = _save

        dto = await service.create_group_room(
            me_id="U_A", title="친친모", member_ids=["U_B", "U_C"],
        )

        assert dto.chat_room_id == "CR_group"
        assert dto.type == ChatRoomType.GROUP
        assert dto.title == "친친모"
        assert dto.peer is None
        assert dto.unread_count == 0

        # members 3명 한 번에 insert
        chat_member_repo_mock.save_all.assert_awaited_once()
        members = chat_member_repo_mock.save_all.call_args.args[0]
        assert {m.user_id for m in members} == {"U_A", "U_B", "U_C"}

        # fan_out_to_user 전원에게 room_joined 3번
        assert fanout_mock.fan_out_to_user.await_count == 3
        assert {c.args[0] for c in fanout_mock.fan_out_to_user.call_args_list} == {
            "U_A", "U_B", "U_C",
        }
        for c in fanout_mock.fan_out_to_user.call_args_list:
            assert c.args[1] == {"type": "room_joined", "room_id": "CR_group"}

    async def test_redis_caches_members_and_unread(
        self, service, friendship_repo_mock, chat_room_repo_mock, redis_mock,
    ):
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B"}

        async def _save(room):
            room.chat_room_id = "CR_new"
            return room
        chat_room_repo_mock.save.side_effect = _save

        await service.create_group_room(
            me_id="U_A", title="T", member_ids=["U_B"],
        )

        # pipeline: gen INCR + sadd + expire(gen, members) + hset (멤버당 unread)
        p = redis_mock._pipes[-1]
        p.incr.assert_called_once()       # room:members:gen bump
        p.sadd.assert_called_once()
        assert p.expire.call_count == 1   # members SET만 TTL; generation fence는 영속
        assert p.hset.call_count == 2     # creator + 1 member


@pytest.mark.unit
class TestInviteMembers:
    async def test_reads_allocated_seq_after_acquiring_room_lock(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        friendship_repo_mock, monkeypatch,
    ):
        room = ChatRoomFactory.create(type_=ChatRoomType.GROUP)
        chat_room_repo_mock.find_by_id.return_value = room
        chat_room_repo_mock.find_by_id_for_update.return_value = room
        chat_member_repo_mock.is_active_member.return_value = True
        chat_member_repo_mock.is_active_member_for_share.return_value = True
        chat_member_repo_mock.find.return_value = None
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B"}

        async def allocated_after_lock(_message_repo, _room_id):
            assert chat_room_repo_mock.find_by_id_for_update.await_count == 1
            return 0

        monkeypatch.setattr(
            RoomService,
            "_get_allocated_current_seq",
            staticmethod(allocated_after_lock),
        )

        await service.invite_members(
            me_id="U_A", room_id="CR_G", user_ids=["U_B"],
        )

    async def test_rejects_new_member_when_room_already_has_100_active_members(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        friendship_repo_mock,
    ):
        room = ChatRoomFactory.create(type_=ChatRoomType.GROUP)
        chat_room_repo_mock.find_by_id.return_value = room
        chat_member_repo_mock.is_active_member.return_value = True
        chat_member_repo_mock.count_active_members.return_value = 100
        chat_member_repo_mock.find.return_value = None
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B"}

        with pytest.raises(ValueError, match="최대 100명"):
            await service.invite_members(
                me_id="U_A", room_id="CR_G", user_ids=["U_B"],
            )

        chat_member_repo_mock.save.assert_not_awaited()

    async def test_capacity_counts_only_targets_that_become_active(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        friendship_repo_mock,
    ):
        room = ChatRoomFactory.create(type_=ChatRoomType.GROUP)
        chat_room_repo_mock.find_by_id.return_value = room
        chat_member_repo_mock.is_active_member.return_value = True
        chat_member_repo_mock.count_active_members.return_value = 99
        active = SimpleNamespace(is_left=False, last_read_message_server_seq=0)
        chat_member_repo_mock.find.side_effect = [active, None]
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B", "U_C"}

        invited, skipped = await service.invite_members(
            me_id="U_A", room_id="CR_G", user_ids=["U_B", "U_C"],
        )

        assert invited == ["U_C"]
        assert skipped == ["U_B"]

    async def test_full_room_still_skips_already_active_target(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        friendship_repo_mock,
    ):
        room = ChatRoomFactory.create(type_=ChatRoomType.GROUP)
        chat_room_repo_mock.find_by_id.return_value = room
        chat_member_repo_mock.is_active_member.return_value = True
        chat_member_repo_mock.count_active_members.return_value = 100
        chat_member_repo_mock.find.return_value = SimpleNamespace(
            is_left=False, last_read_message_server_seq=0,
        )
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B"}

        invited, skipped = await service.invite_members(
            me_id="U_A", room_id="CR_G", user_ids=["U_B"],
        )

        assert invited == []
        assert skipped == ["U_B"]

    async def test_full_room_rejects_rejoin_without_mutating_member(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        friendship_repo_mock,
    ):
        room = ChatRoomFactory.create(type_=ChatRoomType.GROUP)
        chat_room_repo_mock.find_by_id.return_value = room
        chat_member_repo_mock.is_active_member.return_value = True
        chat_member_repo_mock.count_active_members.return_value = 100
        left = SimpleNamespace(
            is_left=True,
            last_read_message_server_seq=7,
            joined_at=None,
            notification_muted=True,
        )
        chat_member_repo_mock.find.return_value = left
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B"}

        with pytest.raises(ValueError, match="최대 100명"):
            await service.invite_members(
                me_id="U_A", room_id="CR_G", user_ids=["U_B"],
            )

        assert left.is_left is True
        assert left.joined_at is None
        assert left.notification_muted is True

    async def test_room_not_found_raises(
        self, service, chat_room_repo_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = None
        with pytest.raises(ChatRoomNotFoundError):
            await service.invite_members(
                me_id="U_A", room_id="CR_X", user_ids=["U_B"],
            )

    async def test_direct_room_raises(self, service, chat_room_repo_mock):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.DIRECT,
        )
        with pytest.raises(ValueError, match="그룹 방에만"):
            await service.invite_members(
                me_id="U_A", room_id="CR_D", user_ids=["U_B"],
            )

    async def test_non_member_inviter_raises(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.is_active_member.return_value = False
        with pytest.raises(PermissionError):
            await service.invite_members(
                me_id="U_X", room_id="CR_G", user_ids=["U_B"],
            )

    async def test_non_friend_target_raises(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        friendship_repo_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.is_active_member.return_value = True
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = set()
        with pytest.raises(ValueError, match="친구가 아닌"):
            await service.invite_members(
                me_id="U_A", room_id="CR_G", user_ids=["U_B"],
            )

    async def test_already_active_member_is_skipped(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        friendship_repo_mock,
    ):
        """이미 활성 멤버 → skipped_already_member 에 포함, save 호출 없음."""
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.is_active_member.return_value = True
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B"}
        chat_member_repo_mock.find.return_value = SimpleNamespace(
            is_left=False, last_read_message_server_seq=5,
        )

        invited, skipped = await service.invite_members(
            me_id="U_A", room_id="CR_G", user_ids=["U_B"],
        )
        assert invited == []
        assert skipped == ["U_B"]
        chat_member_repo_mock.save.assert_not_called()

    async def test_new_member_saves_with_allocated_seq_as_last_read(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        friendship_repo_mock, redis_mock,
    ):
        """신규 멤버는 초대 전에 예약된 in-flight seq까지 과거로 간주한다."""
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.is_active_member.return_value = True
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B"}
        chat_member_repo_mock.find.return_value = None  # 신규
        redis_mock.get.return_value = "42"

        invited, skipped = await service.invite_members(
            me_id="U_A", room_id="CR_G", user_ids=["U_B"],
        )

        assert invited == ["U_B"]
        assert skipped == []
        saved = chat_member_repo_mock.save.call_args.args[0]
        assert saved.user_id == "U_B"
        assert saved.last_read_message_server_seq == 42

    async def test_rejoin_keeps_last_read_and_updates_is_left(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        friendship_repo_mock, redis_mock,
    ):
        """재초대: 기존 member row 의 is_left=false, joined_at 갱신. last_read 는 유지."""
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.is_active_member.return_value = True
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B"}

        existing = SimpleNamespace(
            user_id="U_B",
            is_left=True,
            last_read_message_server_seq=10,
            joined_at=None,
            notification_muted=True,  # 떠나기 전 mute 했었음
        )
        chat_member_repo_mock.find.return_value = existing
        redis_mock.get.return_value = "30"  # current_seq=30

        invited, _ = await service.invite_members(
            me_id="U_A", room_id="CR_G", user_ids=["U_B"],
        )

        assert invited == ["U_B"]
        assert existing.is_left is False
        assert existing.last_read_message_server_seq == 10  # 유지
        assert existing.joined_at is not None
        # 재가입 시 mute 는 NULL 로 리셋 — last_read 와 다른 정책 (docstring 참조).
        assert existing.notification_muted is None
        # seq gap이 아니라 count_after_seq() 실제 메시지 수(기본 mock=0)로 시드한다.
        p = redis_mock._pipes[-1]
        p.hset.assert_any_call(unread_key("U_B"), "CR_G", 0)


@pytest.mark.unit
class TestLeaveRoom:
    async def test_room_not_found_raises(self, service, chat_room_repo_mock):
        chat_room_repo_mock.find_by_id.return_value = None
        with pytest.raises(ChatRoomNotFoundError):
            await service.leave_room(me_id="U_A", room_id="CR_X")

    async def test_direct_room_raises(self, service, chat_room_repo_mock):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.DIRECT,
        )
        with pytest.raises(ValueError, match="그룹 방만"):
            await service.leave_room(me_id="U_A", room_id="CR_D")

    async def test_non_member_raises(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.find.return_value = None
        with pytest.raises(PermissionError):
            await service.leave_room(me_id="U_A", room_id="CR_G")

    async def test_already_left_raises(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.find.return_value = SimpleNamespace(
            is_left=True, last_read_message_server_seq=0,
        )
        with pytest.raises(PermissionError):
            await service.leave_room(me_id="U_A", room_id="CR_G")

    async def test_successful_leave(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        redis_mock, fanout_mock,
    ):
        """SREM + HDEL 먼저 → UPDATE is_left=True → fan_out room_left."""
        room = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP,
        )
        chat_room_repo_mock.find_by_id.return_value = room
        member = SimpleNamespace(is_left=False, last_read_message_server_seq=5)
        chat_member_repo_mock.find.return_value = member

        await service.leave_room(me_id="U_A", room_id="CR_G")

        assert member.is_left is True
        chat_member_repo_mock.update.assert_awaited_once_with(member)

        p = redis_mock._pipes[-1]
        p.srem.assert_called_once()
        p.hdel.assert_called_once()
        p.execute.assert_awaited_once()

        fanout_mock.fan_out_to_user.assert_awaited_once()
        call = fanout_mock.fan_out_to_user.call_args
        assert call.args[0] == "U_A"
        assert call.args[1] == {"type": "room_left", "room_id": "CR_G"}


@pytest.mark.unit
class TestKickMember:
    async def test_self_kick_raises(self, service):
        with pytest.raises(ValueError, match="자기 자신은 강퇴"):
            await service.kick_member(
                me_id="U_A", room_id="CR_G", target_user_id="U_A",
            )

    async def test_room_not_found_raises(self, service, chat_room_repo_mock):
        chat_room_repo_mock.find_by_id.return_value = None
        with pytest.raises(ChatRoomNotFoundError):
            await service.kick_member(
                me_id="U_A", room_id="CR_X", target_user_id="U_B",
            )

    async def test_direct_room_raises(self, service, chat_room_repo_mock):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.DIRECT,
        )
        with pytest.raises(ValueError, match="그룹 방에서만"):
            await service.kick_member(
                me_id="U_A", room_id="CR_D", target_user_id="U_B",
            )

    async def test_non_creator_raises(self, service, chat_room_repo_mock):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.GROUP, creator_id="U_creator",
        )
        with pytest.raises(PermissionError, match="방장"):
            await service.kick_member(
                me_id="U_A", room_id="CR_G", target_user_id="U_B",
            )

    async def test_creator_already_left_raises(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.GROUP, creator_id="U_A",
        )
        chat_member_repo_mock.is_active_member.return_value = False
        with pytest.raises(PermissionError, match="이미 방을 떠난"):
            await service.kick_member(
                me_id="U_A", room_id="CR_G", target_user_id="U_B",
            )

    async def test_target_not_active_raises(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.GROUP, creator_id="U_A",
        )
        chat_member_repo_mock.is_active_member.return_value = True
        chat_member_repo_mock.find.return_value = None
        with pytest.raises(ValueError, match="활성 멤버가 아닙"):
            await service.kick_member(
                me_id="U_A", room_id="CR_G", target_user_id="U_B",
            )

    async def test_successful_kick(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        redis_mock, fanout_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP, creator_id="U_A",
        )
        chat_member_repo_mock.is_active_member.return_value = True
        target = SimpleNamespace(is_left=False, last_read_message_server_seq=0)
        chat_member_repo_mock.find.return_value = target

        await service.kick_member(
            me_id="U_A", room_id="CR_G", target_user_id="U_B",
        )

        assert target.is_left is True
        p = redis_mock._pipes[-1]
        p.srem.assert_called_once()
        p.hdel.assert_called_once()
        fanout_mock.fan_out_to_user.assert_awaited_once()
        call = fanout_mock.fan_out_to_user.call_args
        assert call.args[0] == "U_B"
        assert call.args[1] == {"type": "room_left", "room_id": "CR_G"}


# 시스템 메시지 발행 (PHASE_2 #2) — RoomService 가 MessageService 에 정확한 payload 로
# 위임하는지만 검증. 실제 Mongo 저장/fan-out 은 통합에서.

@pytest.mark.unit
class TestSystemMessageEmission:
    async def test_create_group_emits_created_action(
        self, service, friendship_repo_mock, chat_room_repo_mock, message_service_mock,
    ):
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B"}

        async def _save(room):
            room.chat_room_id = "CR_G"
            return room
        chat_room_repo_mock.save.side_effect = _save

        await service.create_group_room(
            me_id="U_A", title="T", member_ids=["U_B"],
        )

        message_service_mock.send_system_message.assert_awaited_once()
        kwargs = message_service_mock.send_system_message.call_args.kwargs
        assert kwargs["action"] == "created"
        assert kwargs["actor_id"] == "U_A"
        assert kwargs["room_id"] == "CR_G"
        assert kwargs.get("target_ids") is None

    async def test_invite_emits_join_action_with_targets(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        friendship_repo_mock, message_service_mock, redis_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.is_active_member.return_value = True
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B"}
        chat_member_repo_mock.find.return_value = None
        redis_mock.get.return_value = "5"

        await service.invite_members(
            me_id="U_A", room_id="CR_G", user_ids=["U_B"],
        )

        message_service_mock.send_system_message.assert_awaited_once()
        kwargs = message_service_mock.send_system_message.call_args.kwargs
        assert kwargs["action"] == "join"
        assert kwargs["actor_id"] == "U_A"
        assert kwargs["target_ids"] == ["U_B"]

    async def test_invite_system_message_failure_does_not_fail_invite(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        friendship_repo_mock, message_service_mock, redis_mock,
    ):
        """시스템 메시지 발행 실패는 best-effort — 초대 자체(반환값)는 성공해야 한다."""
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.is_active_member.return_value = True
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B"}
        chat_member_repo_mock.find.return_value = None
        redis_mock.get.return_value = "5"
        message_service_mock.send_system_message.side_effect = RuntimeError("mongo down")

        invited, skipped = await service.invite_members(
            me_id="U_A", room_id="CR_G", user_ids=["U_B"],
        )

        assert invited == ["U_B"]  # 시스템 메시지 실패해도 초대 성공

    async def test_invite_with_only_skipped_does_not_emit(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        friendship_repo_mock, message_service_mock,
    ):
        """이미 멤버만 지정 → 실제 초대 0 → 시스템 메시지 불필요."""
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.is_active_member.return_value = True
        friendship_repo_mock.find_accepted_friend_ids_with.return_value = {"U_B"}
        chat_member_repo_mock.find.return_value = SimpleNamespace(
            is_left=False, last_read_message_server_seq=0,
        )

        await service.invite_members(
            me_id="U_A", room_id="CR_G", user_ids=["U_B"],
        )

        message_service_mock.send_system_message.assert_not_awaited()

    async def test_leave_emits_leave_action(
        self, service, chat_room_repo_mock, chat_member_repo_mock, message_service_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.find.return_value = SimpleNamespace(
            is_left=False, last_read_message_server_seq=0,
        )

        await service.leave_room(me_id="U_A", room_id="CR_G")

        message_service_mock.send_system_message.assert_awaited_once()
        kwargs = message_service_mock.send_system_message.call_args.kwargs
        assert kwargs["action"] == "leave"
        assert kwargs["actor_id"] == "U_A"
        assert kwargs.get("target_ids") is None

    async def test_kick_emits_kick_action_with_target(
        self, service, chat_room_repo_mock, chat_member_repo_mock, message_service_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP, creator_id="U_A",
        )
        chat_member_repo_mock.is_active_member.return_value = True
        chat_member_repo_mock.find.return_value = SimpleNamespace(
            is_left=False, last_read_message_server_seq=0,
        )

        await service.kick_member(
            me_id="U_A", room_id="CR_G", target_user_id="U_B",
        )

        message_service_mock.send_system_message.assert_awaited_once()
        kwargs = message_service_mock.send_system_message.call_args.kwargs
        assert kwargs["action"] == "kick"
        assert kwargs["actor_id"] == "U_A"
        assert kwargs["target_ids"] == ["U_B"]
