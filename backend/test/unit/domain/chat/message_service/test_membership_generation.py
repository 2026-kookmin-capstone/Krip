from datetime import datetime, timezone


async def test_stale_leave_generation_does_not_persist_system_message(
    service, chat_member_repo_mock, message_repo_mock, fanout_mock,
):
    chat_member_repo_mock.lock_matching_membership_generations.side_effect = None
    chat_member_repo_mock.lock_matching_membership_generations.return_value = set()

    await service.send_system_message(
        room_id="CR_1",
        action="leave",
        actor_id="U_A",
        required_removed_user_id="U_A",
        required_removed_generation=datetime.now(timezone.utc),
    )

    message_repo_mock.insert.assert_not_awaited()
    fanout_mock.fan_out_to_room.assert_not_awaited()


async def test_stale_join_generation_does_not_persist_system_message(
    service, chat_member_repo_mock, message_repo_mock, fanout_mock,
):
    chat_member_repo_mock.lock_matching_membership_generations.side_effect = None
    chat_member_repo_mock.lock_matching_membership_generations.return_value = set()

    await service.send_system_message(
        room_id="CR_1",
        action="join",
        actor_id="U_A",
        target_ids=["U_B"],
        required_joined_user_ids=["U_B"],
        required_joined_generations={"U_B": datetime.now(timezone.utc)},
    )

    message_repo_mock.insert.assert_not_awaited()
    fanout_mock.fan_out_to_room.assert_not_awaited()
