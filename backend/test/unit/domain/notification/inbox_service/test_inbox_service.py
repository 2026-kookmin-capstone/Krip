"""InboxService — 인박스 + fan-out + cascade 단위 테스트.

검증 대상:
    - fan-out 3종 (feed_like / feed_comment / tripmate_like): 본인→본인 skip, snapshot
      payload 합성, DuplicateKeyError 멱등 swallow, 일반 Exception swallow.
    - 인박스 조회 (`list_items`): 페이지네이션, cursor 형식, naive→UTC 보강,
      mark_as_read 후처리, mark 실패 swallow.
    - 미읽음 카운트 (`count_unread`): 999+ cap.
    - X 버튼 (`hide_item`): atomic 권한 검증, ObjectId 형식 오류 → NotFound.
    - 탈퇴 cascade (`cascade_user_withdrawn`): self-swallow.

InboxRepository 는 mock 이라 mongo 비접근.
"""
from datetime import datetime, timedelta, timezone

import pytest
from beanie import PydanticObjectId
from pymongo.errors import DuplicateKeyError

from app.domain.notification.model.inbox import (
    InboxItem,
    InboxItemType,
    TargetType,
)
from app.domain.notification.service.exception import InboxItemNotFoundError
from app.util.cursor import decode_cursor, encode_cursor
from test.unit.domain.notification.inbox_service.model_factory import (
    InboxItemFactory,
)


@pytest.mark.unit
class TestNotifyFeedLike:
    """Tests for InboxService.notify_feed_like."""

    async def test_self_like_skips_insert(self, service, inbox_repo_mock):
        """본인→본인 좋아요는 fan-out skip — repo.insert 호출 0회."""
        await service.notify_feed_like(
            recipient_id="USER_a",
            actor_id="USER_a",
            actor_name="me",
            actor_profile_image_url=None,
            post_id="FDP_x",
            post_preview=None,
        )

        inbox_repo_mock.insert.assert_not_awaited()

    async def test_inserts_with_snapshot_when_recipient_differs(
        self, service, inbox_repo_mock,
    ):
        """정상 fan-out — InboxItem 인스턴스가 모든 snapshot 필드 포함하여 insert."""
        await service.notify_feed_like(
            recipient_id="USER_owner",
            actor_id="USER_actor",
            actor_name="actorName",
            actor_profile_image_url="https://img/p.jpg",
            post_id="FDP_x",
            post_preview="https://img/thumb.jpg",
        )

        inbox_repo_mock.insert.assert_awaited_once()
        item: InboxItem = inbox_repo_mock.insert.await_args.args[0]
        assert item.recipient_id == "USER_owner"
        assert item.actor_id == "USER_actor"
        assert item.type == InboxItemType.FEED_LIKE
        assert item.target_type == TargetType.FEED_POST
        assert item.target_id == "FDP_x"
        assert item.comment_id is None
        assert item.actor_name == "actorName"
        assert item.actor_profile_image_url == "https://img/p.jpg"
        assert item.target_preview == "https://img/thumb.jpg"

    async def test_duplicate_key_error_is_swallowed(
        self, service, inbox_repo_mock,
    ):
        """좋아요 취소→재좋아요 race 시 dedup unique 충돌 → 멱등 skip, raise 안 됨."""
        inbox_repo_mock.insert.side_effect = DuplicateKeyError("dup")

        await service.notify_feed_like(
            recipient_id="USER_owner",
            actor_id="USER_actor",
            actor_name="x",
            actor_profile_image_url=None,
            post_id="FDP_x",
            post_preview=None,
        )

        inbox_repo_mock.insert.assert_awaited_once()

    async def test_general_exception_is_swallowed(
        self, service, inbox_repo_mock,
    ):
        """Mongo 일시 장애 — best-effort 정책상 swallow + 로그, 응답 정상."""
        inbox_repo_mock.insert.side_effect = RuntimeError("mongo down")

        await service.notify_feed_like(
            recipient_id="USER_owner",
            actor_id="USER_actor",
            actor_name="x",
            actor_profile_image_url=None,
            post_id="FDP_x",
            post_preview=None,
        )


@pytest.mark.unit
class TestNotifyFeedComment:
    """Tests for InboxService.notify_feed_comment."""

    async def test_self_comment_skips_insert(self, service, inbox_repo_mock):
        await service.notify_feed_comment(
            recipient_id="USER_a",
            actor_id="USER_a",
            actor_name="me",
            actor_profile_image_url=None,
            post_id="FDP_x",
            post_preview=None,
            comment_id="CMT_1",
            comment_content="hi",
        )

        inbox_repo_mock.insert.assert_not_awaited()

    async def test_inserts_with_comment_id_and_preview(
        self, service, inbox_repo_mock,
    ):
        await service.notify_feed_comment(
            recipient_id="USER_owner",
            actor_id="USER_actor",
            actor_name="actorName",
            actor_profile_image_url=None,
            post_id="FDP_x",
            post_preview="https://thumb",
            comment_id="CMT_1",
            comment_content="좋은 글이네요",
        )

        item: InboxItem = inbox_repo_mock.insert.await_args.args[0]
        assert item.type == InboxItemType.FEED_COMMENT
        assert item.comment_id == "CMT_1"
        assert item.comment_preview == "좋은 글이네요"

    async def test_long_content_truncated_with_ellipsis(
        self, service, inbox_repo_mock,
    ):
        """100자 초과 본문은 잘리고 ellipsis 추가 — `_truncate_comment` 동작."""
        long_content = "ㄱ" * 150

        await service.notify_feed_comment(
            recipient_id="USER_owner",
            actor_id="USER_actor",
            actor_name="x",
            actor_profile_image_url=None,
            post_id="FDP_x",
            post_preview=None,
            comment_id="CMT_1",
            comment_content=long_content,
        )

        item: InboxItem = inbox_repo_mock.insert.await_args.args[0]
        assert len(item.comment_preview) == 101
        assert item.comment_preview.endswith("…")

    async def test_short_content_kept_as_is(self, service, inbox_repo_mock):
        """100자 이하 본문은 ellipsis 없이 그대로."""
        await service.notify_feed_comment(
            recipient_id="USER_owner",
            actor_id="USER_actor",
            actor_name="x",
            actor_profile_image_url=None,
            post_id="FDP_x",
            post_preview=None,
            comment_id="CMT_1",
            comment_content="짧은 댓글",
        )

        item: InboxItem = inbox_repo_mock.insert.await_args.args[0]
        assert item.comment_preview == "짧은 댓글"
        assert "…" not in item.comment_preview


@pytest.mark.unit
class TestNotifyTripmateLike:
    """Tests for InboxService.notify_tripmate_like."""

    async def test_self_like_skips_insert(self, service, inbox_repo_mock):
        await service.notify_tripmate_like(
            recipient_id="USER_a",
            actor_id="USER_a",
            actor_name="me",
            actor_profile_image_url=None,
            post_id="TMP_x",
            post_preview=None,
        )

        inbox_repo_mock.insert.assert_not_awaited()

    async def test_inserts_with_tripmate_target_type(
        self, service, inbox_repo_mock,
    ):
        """트립메이트 좋아요는 target_type=TRIPMATE_POST, post_preview 는 title 권장."""
        await service.notify_tripmate_like(
            recipient_id="USER_owner",
            actor_id="USER_actor",
            actor_name="actorName",
            actor_profile_image_url=None,
            post_id="TMP_x",
            post_preview="여행 같이 가실 분",
        )

        item: InboxItem = inbox_repo_mock.insert.await_args.args[0]
        assert item.type == InboxItemType.TRIPMATE_LIKE
        assert item.target_type == TargetType.TRIPMATE_POST
        assert item.target_preview == "여행 같이 가실 분"


@pytest.mark.unit
class TestListItems:
    """Tests for InboxService.list_items."""

    async def test_returns_empty_when_no_items(
        self, service, inbox_repo_mock,
    ):
        inbox_repo_mock.find_by_recipient.return_value = []

        result = await service.list_items(recipient_id="USER_a")

        assert result.items == []
        assert result.next_cursor is None

    async def test_no_next_cursor_when_under_page_size(
        self, service, inbox_repo_mock,
    ):
        """fetch 가 limit+1 미만이면 다음 페이지 없음."""
        inbox_repo_mock.find_by_recipient.return_value = [
            InboxItemFactory.create() for _ in range(5)
        ]

        result = await service.list_items(recipient_id="USER_a")

        assert len(result.items) == 5
        assert result.next_cursor is None

    async def test_next_cursor_carries_created_at_and_id_when_has_more(
        self, service, inbox_repo_mock,
    ):
        """fetch 가 limit+1 = 21 이면 has_more, next_cursor 는 20번째 (잘리기 전 마지막) 의
        `(created_at, _id)` 복합키를 opaque 토큰으로 담는다 (같은 ms tiebreak 용)."""
        base = datetime(2025, 1, 1, tzinfo=timezone.utc)
        items = [
            InboxItemFactory.create(created_at=base + timedelta(seconds=i))
            for i in range(21)
        ]
        inbox_repo_mock.find_by_recipient.return_value = items

        result = await service.list_items(recipient_id="USER_a")

        assert len(result.items) == 20
        decoded = decode_cursor(result.next_cursor)
        assert decoded is not None
        assert decoded[0] == items[19].created_at
        assert decoded[1] == str(items[19].id)

    async def test_invalid_cursor_format_raises_value_error(self, service):
        """클라가 손상/위조 토큰을 보내면 router 가 400 매핑하도록 ValueError."""
        with pytest.raises(ValueError, match="cursor"):
            await service.list_items(
                recipient_id="USER_a", cursor="not-an-iso",
            )

    async def test_cursor_decoded_into_keyset_tuple_for_repo(
        self, service, inbox_repo_mock,
    ):
        """opaque 토큰 → repo 에는 `(datetime, ObjectId)` keyset 튜플로 전달."""
        inbox_repo_mock.find_by_recipient.return_value = []
        oid = PydanticObjectId()
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        await service.list_items(
            recipient_id="USER_a", cursor=encode_cursor(ts, str(oid)),
        )

        cursor_key = inbox_repo_mock.find_by_recipient.await_args.kwargs["cursor"]
        assert cursor_key[0] == ts
        assert cursor_key[1] == oid

    async def test_naive_cursor_boosted_to_utc(
        self, service, inbox_repo_mock,
    ):
        """tz 누락 토큰도 UTC 로 보강되어 repo 에 전달 — 외부/구버전 클라 방어."""
        inbox_repo_mock.find_by_recipient.return_value = []
        naive = datetime(2025, 1, 1, 12, 0, 0)

        await service.list_items(
            recipient_id="USER_a", cursor=encode_cursor(naive, str(PydanticObjectId())),
        )

        cursor_dt = inbox_repo_mock.find_by_recipient.await_args.kwargs["cursor"][0]
        assert cursor_dt.tzinfo is not None
        assert cursor_dt.utcoffset() == timedelta(0)

    async def test_aware_cursor_passes_through(
        self, service, inbox_repo_mock,
    ):
        inbox_repo_mock.find_by_recipient.return_value = []
        kst = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=9)))

        await service.list_items(
            recipient_id="USER_a", cursor=encode_cursor(kst, str(PydanticObjectId())),
        )

        cursor_dt = inbox_repo_mock.find_by_recipient.await_args.kwargs["cursor"][0]
        assert cursor_dt.tzinfo is not None
        assert cursor_dt.utcoffset() == timedelta(hours=9)

    async def test_invalid_objectid_in_cursor_raises_value_error(self, service):
        """토큰의 tiebreak 조각이 유효한 ObjectId 가 아니면 400 매핑용 ValueError."""
        ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
        with pytest.raises(ValueError, match="cursor"):
            await service.list_items(
                recipient_id="USER_a", cursor=encode_cursor(ts, "not-an-objectid"),
            )

    async def test_mark_as_read_true_marks_only_fetched_page_ids(
        self, service, inbox_repo_mock,
    ):
        """첫 페이지 진입(mark_as_read=True) → fetch 후, 이번 페이지에 담긴 항목 id 만 read 처리."""
        items = [InboxItemFactory.create() for _ in range(3)]
        inbox_repo_mock.find_by_recipient.return_value = items

        await service.list_items(recipient_id="USER_a", mark_as_read=True)

        inbox_repo_mock.mark_read_by_ids.assert_awaited_once()
        called_recipient, called_ids = inbox_repo_mock.mark_read_by_ids.await_args.args
        assert called_recipient == "USER_a"
        assert called_ids == [i.id for i in items]

    async def test_mark_as_read_does_not_touch_post_fetch_items(
        self, service, inbox_repo_mock,
    ):
        """fetch 스냅샷 이후 concurrent fan-out 으로 들어온 항목은 read 로 눌리지 않는다.

        limit+1(=21) fetch 중 21번째(오버플로우, 페이지에 노출 안 됨)는 mark 대상에서 제외 —
        아직 사용자에게 보이지 않은 항목이 조용히 읽음 처리돼 삼켜지는 것을 방지.
        """
        items = [InboxItemFactory.create() for _ in range(21)]
        inbox_repo_mock.find_by_recipient.return_value = items

        await service.list_items(recipient_id="USER_a", mark_as_read=True)

        called_ids = inbox_repo_mock.mark_read_by_ids.await_args.args[1]
        assert len(called_ids) == 20
        assert items[20].id not in called_ids

    async def test_mark_as_read_false_does_not_mark(
        self, service, inbox_repo_mock,
    ):
        """더 보기(cursor 있음) → read 처리 호출 안 됨."""
        inbox_repo_mock.find_by_recipient.return_value = []

        await service.list_items(recipient_id="USER_a", mark_as_read=False)

        inbox_repo_mock.mark_read_by_ids.assert_not_awaited()

    async def test_mark_read_failure_swallowed(
        self, service, inbox_repo_mock,
    ):
        """mark_read_by_ids Mongo 장애 → swallow, 응답엔 영향 없음."""
        inbox_repo_mock.find_by_recipient.return_value = [
            InboxItemFactory.create(),
        ]
        inbox_repo_mock.mark_read_by_ids.side_effect = RuntimeError("mongo down")

        result = await service.list_items(
            recipient_id="USER_a", mark_as_read=True,
        )

        assert len(result.items) == 1

    async def test_response_is_read_reflects_pre_mark_state(
        self, service, inbox_repo_mock,
    ):
        """dto 변환은 read 처리 전 — 응답엔 read_at=None → is_read=False 그대로.

        클라가 "방금 본 항목" 시각 강조할 수 있도록 한 의도적 순서.
        """
        unread_item = InboxItemFactory.create(read_at=None)
        inbox_repo_mock.find_by_recipient.return_value = [unread_item]

        result = await service.list_items(
            recipient_id="USER_a", mark_as_read=True,
        )

        assert result.items[0].is_read is False


@pytest.mark.unit
class TestCountUnread:
    """Tests for InboxService.count_unread."""

    async def test_returns_raw_when_under_cap(
        self, service, inbox_repo_mock,
    ):
        inbox_repo_mock.count_unread.return_value = 42

        result = await service.count_unread(recipient_id="USER_a")

        assert result == 42

    async def test_capped_at_999(self, service, inbox_repo_mock):
        """repo 가 cap+1 = 1000 반환해도 service 는 999 로 클립 (999+ 표시용)."""
        inbox_repo_mock.count_unread.return_value = 1000

        result = await service.count_unread(recipient_id="USER_a")

        assert result == 999


@pytest.mark.unit
class TestHideItem:
    """Tests for InboxService.hide_item."""

    async def test_hides_when_owned_and_visible(
        self, service, inbox_repo_mock,
    ):
        inbox_repo_mock.hide.return_value = True
        oid = PydanticObjectId()

        await service.hide_item(
            recipient_id="USER_a", inbox_item_id=str(oid),
        )

        inbox_repo_mock.hide.assert_awaited_once_with(oid, "USER_a")

    async def test_invalid_objectid_format_raises_not_found(self, service):
        """잘못된 형식의 id → NotFound (정보 누출 회피)."""
        with pytest.raises(InboxItemNotFoundError, match="존재하지 않는"):
            await service.hide_item(
                recipient_id="USER_a", inbox_item_id="not-an-objectid",
            )

    async def test_other_user_or_missing_raises_not_found(
        self, service, inbox_repo_mock,
    ):
        """repo.hide 가 False (id 미존재 / 타인 소유 / 이미 hide) → NotFound 일원화."""
        inbox_repo_mock.hide.return_value = False

        with pytest.raises(InboxItemNotFoundError, match="존재하지 않는"):
            await service.hide_item(
                recipient_id="USER_a",
                inbox_item_id=str(PydanticObjectId()),
            )


@pytest.mark.unit
class TestCascadeUserWithdrawn:
    """Tests for InboxService.cascade_user_withdrawn.

    게시물/댓글 삭제 cascade 는 정책상 제거됨 — 본 service 에 메서드 자체 없음.
    """

    async def test_deletes_recipient_or_actor_matching(
        self, service, inbox_repo_mock,
    ):
        inbox_repo_mock.delete_by_user.return_value = 7

        deleted = await service.cascade_user_withdrawn(user_id="USER_x")

        assert deleted == 7
        inbox_repo_mock.delete_by_user.assert_awaited_once_with("USER_x")

    async def test_failure_swallowed_returns_zero(
        self, service, inbox_repo_mock,
    ):
        """Mongo 장애 → swallow + 로그, 0 반환 → caller (withdraw worker) 안전."""
        inbox_repo_mock.delete_by_user.side_effect = RuntimeError("mongo down")

        deleted = await service.cascade_user_withdrawn(user_id="USER_x")

        assert deleted == 0
