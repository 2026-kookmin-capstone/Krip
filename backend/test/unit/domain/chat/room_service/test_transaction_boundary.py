"""RoomService 트랜잭션 경계 계약 — DB 파트(`_*_tx`) 실패 시 커밋 후 부수효과 미실행.

멤버십 변경(생성/초대/퇴장/강퇴)의 DB 파트가 raise 하면 Redis 캐시(SADD/SREM)·구독·
fan-out·시스템 메시지가 일어나면 안 된다 — 롤백 시 비멤버가 room:members 캐시에 잔존하는
것을 방지하는 리팩터링의 핵심.
"""
import pytest

from app.domain.chat.service.exception import ChatRoomNotFoundError
from test.unit.domain.chat.room_service.model_factory import ChatRoomFactory


class CommitFailingUnitOfWork:
    def __init__(self, session):
        self._session = session

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        if exc is None:
            raise RuntimeError("commit failed")
        return False


class RecordingUnitOfWork:
    def __init__(self, session, events):
        self._session = session
        self._events = events

    async def __aenter__(self):
        return self._session

    async def __aexit__(self, exc_type, exc, tb):
        if exc is None:
            self._events.append("commit")
        return False


@pytest.mark.unit
class TestTxFailureSkipsSideEffects:
    """DB 파트 실패가 부수효과(Redis/구독/fan-out/시스템 메시지)로 새지 않는지 검증."""

    def _assert_no_side_effects(self, redis_mock, fanout_mock, message_service_mock):
        redis_mock.pipeline.assert_not_called()          # SADD/SREM/HSET(파이프라인) 미실행
        fanout_mock.subscribe_user_to_room.assert_not_awaited()
        fanout_mock.unsubscribe_user_from_room.assert_not_awaited()
        fanout_mock.fan_out_to_user.assert_not_awaited()
        message_service_mock.send_system_message.assert_not_awaited()

    async def test_create_direct_room_failure_skips_emit(
        self, service, redis_mock, fanout_mock, message_service_mock,
    ):
        """1:1 방 생성 DB 파트 실패(자기 자신) → room_joined 캐시/구독/fan-out 미실행."""
        with pytest.raises(ValueError):
            await service.create_direct_room(me_id="U_A", peer_user_id="U_A")

        self._assert_no_side_effects(redis_mock, fanout_mock, message_service_mock)

    async def test_create_group_room_failure_skips_emit(
        self, service, redis_mock, fanout_mock, message_service_mock,
    ):
        """그룹 방 생성 DB 파트 실패(초대 대상 없음) → 캐시/구독/fan-out/시스템 메시지 미실행."""
        with pytest.raises(ValueError):
            await service.create_group_room(me_id="U_A", title="t", member_ids=["U_A"])

        self._assert_no_side_effects(redis_mock, fanout_mock, message_service_mock)

    async def test_invite_members_failure_skips_emit(
        self, service, redis_mock, fanout_mock, message_service_mock,
    ):
        """초대 DB 파트 실패(방 없음) → 초대 부수효과/시스템 메시지 미실행."""
        # chat_room_repo.find_by_id 기본값 None → ChatRoomNotFoundError
        with pytest.raises(ChatRoomNotFoundError):
            await service.invite_members(me_id="U_A", room_id="CR_X", user_ids=["U_B"])

        self._assert_no_side_effects(redis_mock, fanout_mock, message_service_mock)

    async def test_leave_room_failure_skips_emit(
        self, service, redis_mock, fanout_mock, message_service_mock,
    ):
        """퇴장 DB 파트 실패(방 없음) → SREM/구독 해제/room_left/시스템 메시지 미실행."""
        with pytest.raises(ChatRoomNotFoundError):
            await service.leave_room(me_id="U_A", room_id="CR_X")

        self._assert_no_side_effects(redis_mock, fanout_mock, message_service_mock)

    async def test_kick_member_failure_skips_emit(
        self, service, redis_mock, fanout_mock, message_service_mock,
    ):
        """강퇴 DB 파트 실패(자기 자신 강퇴) → SREM/구독 해제/room_left/시스템 메시지 미실행."""
        with pytest.raises(ValueError):
            await service.kick_member(me_id="U_A", room_id="CR_G", target_user_id="U_A")

        self._assert_no_side_effects(redis_mock, fanout_mock, message_service_mock)

    async def test_mark_read_commit_failure_skips_unread_and_fanout(
        self,
        service,
        mock_session,
        chat_room_repo_mock,
        chat_member_repo_mock,
        message_repo_mock,
        lua_mock,
        fanout_mock,
    ):
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G",
        )
        message_repo_mock.get_max_server_seq.return_value = 7
        chat_member_repo_mock.mark_read.return_value = 7
        service.uow = CommitFailingUnitOfWork(mock_session)

        with pytest.raises(RuntimeError, match="commit failed"):
            await service.mark_read(
                me_id="U_A",
                me_session_id="WS_A",
                room_id="CR_G",
                up_to_server_seq=7,
            )

        lua_mock.mark_read_unread.assert_not_awaited()
        fanout_mock.fan_out_to_session.assert_not_awaited()
        fanout_mock.fan_out_to_room.assert_not_awaited()

    async def test_mark_read_side_effects_run_after_commit(
        self,
        service,
        mock_session,
        chat_room_repo_mock,
        chat_member_repo_mock,
        message_repo_mock,
        lua_mock,
        fanout_mock,
    ):
        events = []
        chat_room_repo_mock.find_by_id.return_value = ChatRoomFactory.create(
            chat_room_id="CR_G",
        )
        message_repo_mock.get_max_server_seq.return_value = 7

        async def mark_read(*args):
            events.append("sql_update")
            return 7

        async def sync_unread(**kwargs):
            events.append("unread")
            return [0, 1, 7]

        async def fanout(*args):
            events.append("room_fanout")

        chat_member_repo_mock.mark_read.side_effect = mark_read
        lua_mock.mark_read_unread.side_effect = sync_unread
        fanout_mock.fan_out_to_room.side_effect = fanout
        service.uow = RecordingUnitOfWork(mock_session, events)

        await service.mark_read(
            me_id="U_A",
            me_session_id="WS_A",
            room_id="CR_G",
            up_to_server_seq=7,
        )

        assert events == ["sql_update", "commit", "unread", "room_fanout"]
