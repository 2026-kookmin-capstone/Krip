from datetime import datetime, timezone

from test.unit.domain.chat.room_service.model_factory import ChatRoomFactory


async def test_stale_removed_generation_has_no_side_effects(
    service, chat_room_repo_mock, chat_member_repo_mock, fanout_mock, redis_mock,
):
    generation = datetime.now(timezone.utc)
    chat_room_repo_mock.find_by_id_for_update.return_value = ChatRoomFactory.create(
        chat_room_id="CR_G",
    )
    chat_member_repo_mock.lock_matching_membership_generations.return_value = set()

    await service._emit_member_removed_locked("CR_G", "U_A", generation)

    fanout_mock.fan_out_member_removed.assert_not_awaited()
    assert redis_mock._pipes == []


async def test_stale_joined_generation_has_no_side_effects(
    service, chat_room_repo_mock, chat_member_repo_mock, fanout_mock, redis_mock,
):
    generation = datetime.now(timezone.utc)
    chat_room_repo_mock.find_by_id_for_update.return_value = ChatRoomFactory.create(
        chat_room_id="CR_G",
    )
    chat_member_repo_mock.lock_active_receiving_user_ids.return_value = {"U_A"}
    chat_member_repo_mock.lock_matching_membership_generations.return_value = set()

    result = await service._emit_invite_side_effects_locked(
        "CR_G",
        invited=["U_A"],
        new_members=["U_A"],
        rejoined=[],
        expected_generations={"U_A": generation},
    )

    assert result == []
    fanout_mock.fan_out_member_joined.assert_not_awaited()
    assert redis_mock._pipes == []


async def test_stale_initial_group_generation_has_no_side_effects(
    service, chat_room_repo_mock, chat_member_repo_mock, fanout_mock, redis_mock,
):
    generation = datetime.now(timezone.utc)
    chat_room_repo_mock.find_by_id_for_update.return_value = ChatRoomFactory.create(
        chat_room_id="CR_G",
    )
    chat_member_repo_mock.lock_active_receiving_user_ids.return_value = {"U_A"}
    chat_member_repo_mock.lock_matching_membership_generations.return_value = set()

    result = await service._emit_room_joined_locked(
        "CR_G",
        ["U_A"],
        unread_seed="zero",
        expected_generations={"U_A": generation},
    )

    assert result == []
    fanout_mock.subscribe_user_to_room.assert_not_awaited()
    fanout_mock.fan_out_member_joined.assert_not_awaited()
    assert redis_mock._pipes == []
