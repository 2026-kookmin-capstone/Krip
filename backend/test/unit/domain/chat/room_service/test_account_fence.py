import pytest

from test.unit.domain.chat.room_service.model_factory import ChatRoomFactory


@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        ("create_direct_room", {"me_id": "U_A", "peer_user_id": "U_B"}),
        (
            "create_group_room",
            {"me_id": "U_A", "title": "room", "member_ids": ["U_B"]},
        ),
        ("invite_members", {"me_id": "U_A", "room_id": "CR_G", "user_ids": ["U_B"]}),
        ("leave_room", {"me_id": "U_A", "room_id": "CR_G"}),
        (
            "kick_member",
            {"me_id": "U_A", "room_id": "CR_G", "target_user_id": "U_B"},
        ),
        (
            "mark_read",
            {
                "me_id": "U_A",
                "me_session_id": "WS_A",
                "room_id": "CR_G",
                "up_to_server_seq": 1,
            },
        ),
    ],
)
async def test_room_mutations_recheck_active_account_in_transaction(
    service, user_repo_mock, chat_room_repo_mock, method_name, kwargs,
):
    if method_name == "create_direct_room":
        user_repo_mock.find_by_id_with_profile.return_value = object()
    batch_methods = {"create_direct_room", "create_group_room", "invite_members"}
    if method_name in batch_methods:
        user_repo_mock.lock_active_user_ids.side_effect = None
        user_repo_mock.lock_active_user_ids.return_value = {"U_B"}
    else:
        user_repo_mock.lock_if_active.return_value = False
    if method_name == "mark_read":
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G",
        )

    with pytest.raises(PermissionError, match="비활성 계정"):
        await getattr(service, method_name)(**kwargs)

    if method_name in batch_methods:
        expected_ids = {"U_A", "U_B"}
        user_repo_mock.lock_active_user_ids.assert_awaited_once_with(expected_ids)
    else:
        user_repo_mock.lock_if_active.assert_awaited_once_with("U_A")


@pytest.mark.parametrize(
    ("method_name", "kwargs"),
    [
        ("create_direct_room", {"me_id": "U_A", "peer_user_id": "U_B"}),
        (
            "create_group_room",
            {"me_id": "U_A", "title": "room", "member_ids": ["U_B"]},
        ),
        ("invite_members", {"me_id": "U_A", "room_id": "CR_G", "user_ids": ["U_B"]}),
    ],
)
async def test_membership_grants_reject_inactive_targets(
    service, user_repo_mock, method_name, kwargs,
):
    if method_name == "create_direct_room":
        user_repo_mock.find_by_id_with_profile.return_value = object()
    user_repo_mock.lock_active_user_ids.side_effect = None
    user_repo_mock.lock_active_user_ids.return_value = {"U_A"}

    with pytest.raises(ValueError, match="비활성 계정"):
        await getattr(service, method_name)(**kwargs)
