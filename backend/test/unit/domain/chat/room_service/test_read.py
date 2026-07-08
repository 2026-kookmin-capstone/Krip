"""RoomService.mark_read 단위 테스트 (PHASE_2 #3).

read op 는 **GREATEST 로 regress 방지**, **unread 를 DB 잔여 기준 재계산**(부분 읽기·동시
도착 손실 방지, 999+ 캡), **read_ack 발신 세션 직송 + read 이벤트 방 브로드캐스트** 를
수행. mock 레벨에서 각 단계 호출과 payload 를 정확히 검증한다.
"""
from test.unit.domain.chat.room_service.model_factory import ChatRoomFactory
import pytest

from app.domain.chat.service.exception import ChatRoomNotFoundError
from app.domain.chat.model.chat_room import ChatRoomType


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
        message_repo_mock, redis_mock, fanout_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.mark_read.return_value = 7  # regress 적용 후 최종 seq
        message_repo_mock.count_after_seq.return_value = 0  # 최신까지 읽음 → 잔여 0

        result = await service.mark_read(
            me_id="U_A", me_session_id="WS_A", room_id="CR_G",
            up_to_server_seq=5,
        )

        assert result == 7

        # mark_read 가 repository 에 올바른 인자로 위임됐는지
        chat_member_repo_mock.mark_read.assert_awaited_once_with("CR_G", "U_A", 5)

        # Redis unread 을 DB 잔여(final_seq 이후 개수) 기준으로 재계산 — 여기선 0
        redis_mock.hset.assert_awaited_once()
        args = redis_mock.hset.call_args.args
        assert args[0] == "unread:U_A"
        assert args[1] == "CR_G"
        assert args[2] == 0

        # read_ack 발신 세션 직송
        fanout_mock.fan_out_to_session.assert_awaited_once()
        sess_args = fanout_mock.fan_out_to_session.call_args.args
        assert sess_args[0] == "WS_A"
        assert sess_args[1] == {
            "type": "read_ack", "room_id": "CR_G", "up_to_server_seq": 7,
        }

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


    async def test_partial_read_sets_unread_to_residual_not_zero(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        message_repo_mock, redis_mock,
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
        args = redis_mock.hset.call_args.args
        assert args == ("unread:U_A", "CR_G", 3)  # 0 이 아니라 잔여 3


    async def test_unread_capped_at_999(
        self, service, chat_room_repo_mock, chat_member_repo_mock,
        message_repo_mock, redis_mock,
    ):
        """잔여가 1000(=limit) 이상이면 999 로 캡 — recover 경로와 동일 규약."""
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G", type_=ChatRoomType.GROUP,
        )
        chat_member_repo_mock.mark_read.return_value = 2
        message_repo_mock.count_after_seq.return_value = 1000  # limit 만큼 카운트됨

        await service.mark_read(
            me_id="U_A", me_session_id="WS_A", room_id="CR_G",
            up_to_server_seq=1,
        )

        assert redis_mock.hset.call_args.args[2] == 999


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
