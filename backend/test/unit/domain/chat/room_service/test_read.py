"""RoomService.mark_read 단위 테스트 (PHASE_2 #3).

read op 는 **GREATEST 로 regress 방지**, **unread 를 DB 잔여 기준 재계산**(부분 읽기·동시
도착 손실 방지, 999+ 캡), **read 이벤트 방 브로드캐스트** 를 수행한다. `read_ack`은 서비스
완료 후 WebSocket router가 직송한다. mock 레벨에서 각 단계 호출과 payload 를 검증한다.
"""
import pytest

from app.domain.chat.model.chat_room import ChatRoomType
from app.domain.chat.service.exception import ChatRoomNotFoundError
from test.unit.domain.chat.room_service.model_factory import ChatRoomFactory


@pytest.mark.unit
class TestMarkRead:
    async def test_raises_on_zero_or_negative_seq(self, service):
        with pytest.raises(ValueError, match="1 이상"):
            await service.mark_read(
                me_id="U_A", me_session_id="WS_A", room_id="CR_G",
                up_to_server_seq=0,
            )
        with pytest.raises(ValueError, match="1 이상"):
            await service.mark_read(
                me_id="U_A", me_session_id="WS_A", room_id="CR_G",
                up_to_server_seq=-1,
            )

    async def test_raises_room_not_found(
        self, service, chat_room_repo_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = None
        with pytest.raises(ChatRoomNotFoundError):
            await service.mark_read(
                me_id="U_A", me_session_id="WS_A", room_id="CR_X",
                up_to_server_seq=5,
            )

    async def test_non_member_raises_permission_error(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.mark_read.return_value = None  # 활성 멤버 아님
        with pytest.raises(PermissionError):
            await service.mark_read(
                me_id="U_A", me_session_id="WS_A", room_id="CR_G",
                up_to_server_seq=5,
            )

    async def test_successful_mark_read_recalculates_unread_and_fans_out(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        message_repo_mock, redis_mock, lua_mock, fanout_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP,
        )
        message_repo_mock.get_max_server_seq.return_value = 7  # 방 현재 seq (clamp 상한)
        chat_member_repo_mock.mark_read.return_value = 7  # regress 적용 후 최종 seq
        message_repo_mock.count_after_seq.return_value = 0  # 최신까지 읽음 → 잔여 0

        result = await service.mark_read(
            me_id="U_A", me_session_id="WS_A", room_id="CR_G",
            up_to_server_seq=5,
        )

        assert result == 7

        # mark_read 가 repository 에 올바른 인자로 위임됐는지 (5 <= 현재 7 이라 그대로)
        chat_member_repo_mock.mark_read.assert_awaited_once_with("CR_G", "U_A", 5)

        # unread 을 DB 잔여(final_seq 이후 개수) 기준으로 Lua 재계산 — 여기선 residual=0.
        # unread + read cursor를 final_seq 기준으로 Lua에서 원자 반영한다.
        lua_mock.mark_read_unread.assert_awaited_once()
        call = lua_mock.mark_read_unread.call_args
        assert call.kwargs["keys"] == [
            "unread:U_A", "unread:read_seq:U_A", "room:members:gen:CR_G",
        ]
        assert call.kwargs["args"][0] == "CR_G"   # room_id (hash field)
        assert call.kwargs["args"][1] == 0        # residual
        assert call.kwargs["args"][3] == 999      # cap
        assert call.kwargs["args"][4] == 7        # DB commit의 final_seq
        assert call.kwargs["args"][6] == 0        # read 시작 시 membership generation

        # ACK 는 commit/post-commit 완료 후 router 가 현재 WebSocket 에 직접 전송한다.
        fanout_mock.fan_out_to_session.assert_not_awaited()

        # 방에 read 이벤트 브로드캐스트 (sender_session_id 로 자기 에코 차단)
        fanout_mock.fan_out_to_room.assert_awaited_once()
        room_args = fanout_mock.fan_out_to_room.call_args.args
        assert room_args[0] == "CR_G"
        assert room_args[1] == {
            "type": "read",
            "user_id": "U_A",
            "sender_session_id": "WS_A",
            "up_to_server_seq": 7,
        }

    async def test_clamps_up_to_seq_to_current_room_seq(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        message_repo_mock, redis_mock,
    ):
        """클라가 방 현재 seq 를 넘는 값을 보내면 현재 seq 로 clamp — 미래 포인터 오염 방지."""
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP,
        )
        redis_mock.get.return_value = None
        message_repo_mock.get_max_server_seq.return_value = 12  # 방 현재 seq
        chat_member_repo_mock.mark_read.return_value = 12

        await service.mark_read(
            me_id="U_A", me_session_id="WS_A", room_id="CR_G",
            up_to_server_seq=10**15,  # 악의적 미래 값
        )

        # 10^15 가 아니라 현재 seq(12)로 clamp 되어 위임돼야 한다
        chat_member_repo_mock.mark_read.assert_awaited_once_with("CR_G", "U_A", 12)

    async def test_partial_read_sets_unread_to_residual_not_zero(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        message_repo_mock, lua_mock,
    ):
        """부분 읽기(up_to < 최신) → unread 를 0 이 아니라 DB 잔여 개수로 반영."""
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.mark_read.return_value = 7  # final_seq
        message_repo_mock.count_after_seq.return_value = 3  # 7 이후 잔여 3건

        await service.mark_read(
            me_id="U_A", me_session_id="WS_A", room_id="CR_G",
            up_to_server_seq=5,
        )

        # 잔여는 final_seq(7) 이후로 DB 재계산 (recover 경로와 동일 인자)
        message_repo_mock.count_after_seq.assert_awaited_once_with(
            chat_room_id="CR_G", after_seq=7, limit=1000,
        )
        call = lua_mock.mark_read_unread.call_args
        assert call.kwargs["keys"] == [
            "unread:U_A", "unread:read_seq:U_A", "room:members:gen:CR_G",
        ]
        assert call.kwargs["args"][0] == "CR_G"
        assert call.kwargs["args"][1] == 3  # residual (0 이 아니라 잔여 3) 를 Lua 로 전달
        assert call.kwargs["args"][4] == 7

    async def test_unread_capped_at_999(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        message_repo_mock, lua_mock,
    ):
        """잔여가 1000(=limit) 이상이면 cap(999) 을 Lua 로 전달 — 실제 clamp 는 통합 테스트."""
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.mark_read.return_value = 2
        message_repo_mock.count_after_seq.return_value = 1000  # limit 만큼 카운트됨

        await service.mark_read(
            me_id="U_A", me_session_id="WS_A", room_id="CR_G",
            up_to_server_seq=1,
        )

        call = lua_mock.mark_read_unread.call_args
        assert call.kwargs["args"][1] == 1000  # residual 원값 전달
        assert call.kwargs["args"][3] == 999   # cap 전달 (Lua 가 min 적용)

    async def test_returns_repository_final_seq_even_when_regressed(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
    ):
        """클라가 과거 seq 를 보내도 GREATEST 로 올라간 값이 그대로 돌아온다 (regress 무시)."""
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.mark_read.return_value = 20  # 이미 20 까지 읽은 상태

        result = await service.mark_read(
            me_id="U_A", me_session_id="WS_A", room_id="CR_G",
            up_to_server_seq=5,
        )
        assert result == 20

    async def test_stale_post_commit_read_retries_fanout_with_effective_seq(
        self,
        service,
        chat_room_repo_mock,
        chat_member_repo_mock,
        lua_mock,
        fanout_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.mark_read.return_value = 10
        # 다른 세션의 seq=20 post-commit 반영이 먼저 끝난 상태.
        lua_mock.mark_read_unread.return_value = [0, 0, 20]

        result = await service.mark_read(
            me_id="U_A", me_session_id="WS_A", room_id="CR_G",
            up_to_server_seq=10,
        )

        assert result == 20
        fanout_mock.fan_out_to_room.assert_awaited_once_with(
            "CR_G",
            {
                "type": "read",
                "user_id": "U_A",
                "sender_session_id": "WS_A",
                "up_to_server_seq": 20,
            },
        )

    async def test_equal_post_commit_retry_retries_room_fanout(
        self,
        service,
        chat_room_repo_mock,
        chat_member_repo_mock,
        lua_mock,
        fanout_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.mark_read.return_value = 10
        lua_mock.mark_read_unread.return_value = [0, 2, 10]

        result = await service.mark_read(
            me_id="U_A", me_session_id="WS_A", room_id="CR_G",
            up_to_server_seq=10,
        )

        assert result == 10
        fanout_mock.fan_out_to_room.assert_awaited_once()

    async def test_membership_generation_change_blocks_post_commit_fanout(
        self,
        service,
        chat_room_repo_mock,
        chat_member_repo_mock,
        lua_mock,
        fanout_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.mark_read.return_value = 10
        lua_mock.mark_read_unread.return_value = [0, 3, 10]

        with pytest.raises(RuntimeError, match="멤버십이 변경"):
            await service.mark_read(
                me_id="U_A", me_session_id="WS_A", room_id="CR_G",
                up_to_server_seq=10,
            )

        fanout_mock.fan_out_to_room.assert_not_awaited()
