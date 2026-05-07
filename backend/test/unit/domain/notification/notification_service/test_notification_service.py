"""NotificationService — 알림창 + fan-out + cascade 단위 테스트.

검증 대상:
    - fan-out 3종 (feed_like / feed_comment / tripmate_like): 본인→본인 skip, snapshot
      payload 합성, DuplicateKeyError 멱등 swallow, 일반 Exception swallow.
    - 알림창 조회 (`list_notifications`): 페이지네이션, cursor 형식, naive→UTC 보강,
      mark_as_read 후처리, mark 실패 swallow.
    - 미읽음 카운트 (`count_unread`): 999+ cap.
    - X 버튼 (`hide_notification`): atomic 권한 검증, ObjectId 형식 오류 → NotFound.
    - 탈퇴 cascade (`cascade_user_withdrawn`): self-swallow.

NotificationRepository 는 mock 이라 mongo 비접근.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import call

import pytest
from beanie import PydanticObjectId
from pymongo.errors import DuplicateKeyError

from app.domain.notification.model.notification import (
    Notification,
    NotificationType,
    TargetType,
)
from app.domain.notification.service.exception import NotificationNotFoundError

from test.unit.domain.notification.notification_service.model_factory import (
    NotificationFactory,
)


# ──────────────────────────────────────────────────────────────────
# notify_feed_like — 피드 좋아요 fan-out
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestNotifyFeedLike:
    """Tests for NotificationService.notify_feed_like."""

    async def test_self_like_skips_insert(self, service, notification_repo_mock):
        """본인→본인 좋아요는 fan-out skip — repo.insert 호출 0회."""
        await service.notify_feed_like(
            recipient_id="USER_a",
            actor_id="USER_a",  # 동일
            actor_name="me",
            actor_profile_image_url=None,
            post_id="FDP_x",
            post_preview=None,
        )

        notification_repo_mock.insert.assert_not_awaited()

    async def test_inserts_with_snapshot_when_recipient_differs(
        self, service, notification_repo_mock,
    ):
        """정상 fan-out — Notification 인스턴스가 모든 snapshot 필드 포함하여 insert."""
        await service.notify_feed_like(
            recipient_id="USER_owner",
            actor_id="USER_actor",
            actor_name="actorName",
            actor_profile_image_url="https://img/p.jpg",
            post_id="FDP_x",
            post_preview="https://img/thumb.jpg",
        )

        notification_repo_mock.insert.assert_awaited_once()
        notif: Notification = notification_repo_mock.insert.await_args.args[0]
        assert notif.recipient_id == "USER_owner"
        assert notif.actor_id == "USER_actor"
        assert notif.type == NotificationType.FEED_LIKE
        assert notif.target_type == TargetType.FEED_POST
        assert notif.target_id == "FDP_x"
        assert notif.comment_id is None
        assert notif.actor_name == "actorName"
        assert notif.actor_profile_image_url == "https://img/p.jpg"
        assert notif.target_preview == "https://img/thumb.jpg"

    async def test_duplicate_key_error_is_swallowed(
        self, service, notification_repo_mock,
    ):
        """좋아요 취소→재좋아요 race 시 dedup unique 충돌 → 멱등 skip, raise 안 됨."""
        notification_repo_mock.insert.side_effect = DuplicateKeyError("dup")

        # raise 없이 정상 종료해야 함
        await service.notify_feed_like(
            recipient_id="USER_owner",
            actor_id="USER_actor",
            actor_name="x",
            actor_profile_image_url=None,
            post_id="FDP_x",
            post_preview=None,
        )

        notification_repo_mock.insert.assert_awaited_once()

    async def test_general_exception_is_swallowed(
        self, service, notification_repo_mock,
    ):
        """Mongo 일시 장애 — best-effort 정책상 swallow + 로그, 응답 정상."""
        notification_repo_mock.insert.side_effect = RuntimeError("mongo down")

        # raise 없이 정상 종료
        await service.notify_feed_like(
            recipient_id="USER_owner",
            actor_id="USER_actor",
            actor_name="x",
            actor_profile_image_url=None,
            post_id="FDP_x",
            post_preview=None,
        )


# ──────────────────────────────────────────────────────────────────
# notify_feed_comment — 피드 댓글 fan-out
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestNotifyFeedComment:
    """Tests for NotificationService.notify_feed_comment."""

    async def test_self_comment_skips_insert(self, service, notification_repo_mock):
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

        notification_repo_mock.insert.assert_not_awaited()

    async def test_inserts_with_comment_id_and_preview(
        self, service, notification_repo_mock,
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

        notif: Notification = notification_repo_mock.insert.await_args.args[0]
        assert notif.type == NotificationType.FEED_COMMENT
        assert notif.comment_id == "CMT_1"
        assert notif.comment_preview == "좋은 글이네요"

    async def test_long_content_truncated_with_ellipsis(
        self, service, notification_repo_mock,
    ):
        """100자 초과 본문은 잘리고 ellipsis 추가 — `_truncate_comment` 동작."""
        long_content = "ㄱ" * 150  # 150자

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

        notif: Notification = notification_repo_mock.insert.await_args.args[0]
        assert len(notif.comment_preview) == 101  # 100 + "…"
        assert notif.comment_preview.endswith("…")

    async def test_short_content_kept_as_is(self, service, notification_repo_mock):
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

        notif: Notification = notification_repo_mock.insert.await_args.args[0]
        assert notif.comment_preview == "짧은 댓글"
        assert "…" not in notif.comment_preview


# ──────────────────────────────────────────────────────────────────
# notify_tripmate_like — 트립메이트 좋아요 fan-out
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestNotifyTripmateLike:
    """Tests for NotificationService.notify_tripmate_like."""

    async def test_self_like_skips_insert(self, service, notification_repo_mock):
        await service.notify_tripmate_like(
            recipient_id="USER_a",
            actor_id="USER_a",
            actor_name="me",
            actor_profile_image_url=None,
            post_id="TMP_x",
            post_preview=None,
        )

        notification_repo_mock.insert.assert_not_awaited()

    async def test_inserts_with_tripmate_target_type(
        self, service, notification_repo_mock,
    ):
        """트립메이트 좋아요는 target_type=TRIPMATE_POST, post_preview 는 title 권장."""
        await service.notify_tripmate_like(
            recipient_id="USER_owner",
            actor_id="USER_actor",
            actor_name="actorName",
            actor_profile_image_url=None,
            post_id="TMP_x",
            post_preview="여행 같이 가실 분",  # 게시글 title
        )

        notif: Notification = notification_repo_mock.insert.await_args.args[0]
        assert notif.type == NotificationType.TRIPMATE_LIKE
        assert notif.target_type == TargetType.TRIPMATE_POST
        assert notif.target_preview == "여행 같이 가실 분"


# ──────────────────────────────────────────────────────────────────
# list_notifications — 알림창 페이지네이션 + 자동 읽음 처리
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestListNotifications:
    """Tests for NotificationService.list_notifications."""

    async def test_returns_empty_when_no_notifications(
        self, service, notification_repo_mock,
    ):
        notification_repo_mock.find_by_recipient.return_value = []

        result = await service.list_notifications(recipient_id="USER_a")

        assert result.notifications == []
        assert result.next_cursor is None

    async def test_no_next_cursor_when_under_page_size(
        self, service, notification_repo_mock,
    ):
        """fetch 가 limit+1 미만이면 다음 페이지 없음."""
        notification_repo_mock.find_by_recipient.return_value = [
            NotificationFactory.create() for _ in range(5)
        ]

        result = await service.list_notifications(recipient_id="USER_a")

        assert len(result.notifications) == 5
        assert result.next_cursor is None

    async def test_next_cursor_is_last_item_iso_when_has_more(
        self, service, notification_repo_mock,
    ):
        """fetch 가 limit+1 = 21 이면 has_more, next_cursor 는 20번째 (잘리기 전 마지막) 의 created_at."""
        # PAGE_SIZE = 20 가정. 21개 반환 (limit+1)
        base = datetime(2025, 1, 1, tzinfo=timezone.utc)
        notifs = [
            NotificationFactory.create(created_at=base + timedelta(seconds=i))
            for i in range(21)
        ]
        notification_repo_mock.find_by_recipient.return_value = notifs

        result = await service.list_notifications(recipient_id="USER_a")

        assert len(result.notifications) == 20  # cursor 잘림
        # 잘린 후 마지막 (인덱스 19) 의 created_at
        assert result.next_cursor == notifs[19].created_at.isoformat()

    async def test_invalid_cursor_format_raises_value_error(self, service):
        """클라가 ISO 가 아닌 cursor 보내면 router 가 400 매핑하도록 ValueError."""
        with pytest.raises(ValueError, match="cursor"):
            await service.list_notifications(
                recipient_id="USER_a", cursor="not-an-iso",
            )

    async def test_naive_cursor_boosted_to_utc(
        self, service, notification_repo_mock,
    ):
        """tz 누락 ISO 도 UTC 로 보강되어 repo 에 전달 — 외부 클라 방어."""
        notification_repo_mock.find_by_recipient.return_value = []

        await service.list_notifications(
            recipient_id="USER_a", cursor="2025-01-01T12:00:00",  # naive
        )

        cursor_dt = notification_repo_mock.find_by_recipient.await_args.kwargs["cursor"]
        assert cursor_dt.tzinfo is not None
        assert cursor_dt.utcoffset() == timedelta(0)

    async def test_aware_cursor_passes_through(
        self, service, notification_repo_mock,
    ):
        notification_repo_mock.find_by_recipient.return_value = []

        await service.list_notifications(
            recipient_id="USER_a", cursor="2025-01-01T12:00:00+09:00",  # KST
        )

        cursor_dt = notification_repo_mock.find_by_recipient.await_args.kwargs["cursor"]
        assert cursor_dt.tzinfo is not None
        assert cursor_dt.utcoffset() == timedelta(hours=9)

    async def test_mark_as_read_true_calls_mark_all_read(
        self, service, notification_repo_mock,
    ):
        """첫 페이지 진입(mark_as_read=True) → fetch 후 mark_all_read 호출."""
        notification_repo_mock.find_by_recipient.return_value = []

        await service.list_notifications(recipient_id="USER_a", mark_as_read=True)

        notification_repo_mock.mark_all_read.assert_awaited_once_with("USER_a")

    async def test_mark_as_read_false_does_not_call_mark_all_read(
        self, service, notification_repo_mock,
    ):
        """더 보기(cursor 있음) → mark_all_read 호출 안 됨."""
        notification_repo_mock.find_by_recipient.return_value = []

        await service.list_notifications(recipient_id="USER_a", mark_as_read=False)

        notification_repo_mock.mark_all_read.assert_not_awaited()

    async def test_mark_all_read_failure_swallowed(
        self, service, notification_repo_mock,
    ):
        """mark_all_read Mongo 장애 → swallow, 응답엔 영향 없음."""
        notification_repo_mock.find_by_recipient.return_value = [
            NotificationFactory.create(),
        ]
        notification_repo_mock.mark_all_read.side_effect = RuntimeError("mongo down")

        # raise 없이 정상 종료
        result = await service.list_notifications(
            recipient_id="USER_a", mark_as_read=True,
        )

        assert len(result.notifications) == 1

    async def test_response_is_read_reflects_pre_mark_state(
        self, service, notification_repo_mock,
    ):
        """dto 변환은 mark_all_read 전 — 응답엔 read_at=None → is_read=False 그대로.

        클라가 "방금 본 알림" 시각 강조할 수 있도록 한 의도적 순서.
        """
        unread_notif = NotificationFactory.create(read_at=None)
        notification_repo_mock.find_by_recipient.return_value = [unread_notif]

        result = await service.list_notifications(
            recipient_id="USER_a", mark_as_read=True,
        )

        # 응답 dto 의 is_read 는 mark 전 상태 (False) — DB 만 update
        assert result.notifications[0].is_read is False


# ──────────────────────────────────────────────────────────────────
# count_unread — 미읽음 뱃지
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestCountUnread:
    """Tests for NotificationService.count_unread."""

    async def test_returns_raw_when_under_cap(
        self, service, notification_repo_mock,
    ):
        notification_repo_mock.count_unread.return_value = 42

        result = await service.count_unread(recipient_id="USER_a")

        assert result == 42

    async def test_capped_at_999(self, service, notification_repo_mock):
        """repo 가 cap+1 = 1000 반환해도 service 는 999 로 클립 (999+ 표시용)."""
        notification_repo_mock.count_unread.return_value = 1000

        result = await service.count_unread(recipient_id="USER_a")

        assert result == 999


# ──────────────────────────────────────────────────────────────────
# hide_notification — X 버튼
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestHideNotification:
    """Tests for NotificationService.hide_notification."""

    async def test_hides_when_owned_and_visible(
        self, service, notification_repo_mock,
    ):
        notification_repo_mock.hide.return_value = True
        oid = PydanticObjectId()

        # raise 없이 정상 종료
        await service.hide_notification(
            recipient_id="USER_a", notification_id=str(oid),
        )

        notification_repo_mock.hide.assert_awaited_once_with(oid, "USER_a")

    async def test_invalid_objectid_format_raises_not_found(self, service):
        """잘못된 형식의 id → NotFound (정보 누출 회피)."""
        with pytest.raises(NotificationNotFoundError, match="존재하지 않는"):
            await service.hide_notification(
                recipient_id="USER_a", notification_id="not-an-objectid",
            )

    async def test_other_user_or_missing_raises_not_found(
        self, service, notification_repo_mock,
    ):
        """repo.hide 가 False (id 미존재 / 타인 소유 / 이미 hide) → NotFound 일원화."""
        notification_repo_mock.hide.return_value = False

        with pytest.raises(NotificationNotFoundError, match="존재하지 않는"):
            await service.hide_notification(
                recipient_id="USER_a",
                notification_id=str(PydanticObjectId()),
            )


# ──────────────────────────────────────────────────────────────────
# cascade_user_withdrawn — 탈퇴 cascade
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestCascadeUserWithdrawn:
    """Tests for NotificationService.cascade_user_withdrawn.

    게시물/댓글 삭제 cascade 는 정책상 제거됨 — 본 service 에 메서드 자체 없음.
    """

    async def test_deletes_recipient_or_actor_matching(
        self, service, notification_repo_mock,
    ):
        notification_repo_mock.delete_by_user.return_value = 7

        deleted = await service.cascade_user_withdrawn(user_id="USER_x")

        assert deleted == 7
        notification_repo_mock.delete_by_user.assert_awaited_once_with("USER_x")

    async def test_failure_swallowed_returns_zero(
        self, service, notification_repo_mock,
    ):
        """Mongo 장애 → swallow + 로그, 0 반환 → caller (withdraw worker) 안전."""
        notification_repo_mock.delete_by_user.side_effect = RuntimeError("mongo down")

        # raise 없이 0 반환
        deleted = await service.cascade_user_withdrawn(user_id="USER_x")

        assert deleted == 0
