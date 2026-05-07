"""알림 서비스 — fan-out 진입점 + 알림창 조회 / hide + cascade.

설계:
    - **stateless** — RDB session 안 쓰고 Mongo (beanie) 단독. UoW 의존성 없음.
      caller (feed/tripmate service) 가 actor 정보 (닉네임/프로필 이미지) 와 target
      preview 를 채워서 fan-out 메서드에 넘긴다 — service 는 단순 insert 에 집중.
    - **fan-out best-effort** — RDB 트랜잭션 *밖* 에서 호출되어야 함 (caller 책임).
      `DuplicateKeyError` 는 멱등 skip, 그 외 예외는 로그만 + 응답 정상. Mongo 일시 장애로
      알림 1건 누락되어도 사용자 액션(좋아요/댓글) 응답에는 영향 없음.
    - **본인→본인 알림 skip** — `recipient_id == actor_id` 는 모든 fan-out 진입점에서 가드.
    - **mute 분리** — 알림창은 mute 영향 없음. 푸시(FCM) 만 mute 가드 적용.

API 매핑:
    notify_feed_like     ← feed_post_like.add_like
    notify_feed_comment  ← feed_post_comment.create_comment
    notify_tripmate_like ← tripmate_post_like.add_like

cascade 호출 매핑:
    cascade_post_deleted     ← feed_post / tripmate_post 삭제 service
    cascade_comment_deleted  ← feed_post_comment 삭제 service
    cascade_user_withdrawn   ← withdraw_purge worker
"""
from typing import Optional
from pymongo.errors import DuplicateKeyError
from datetime import datetime, timezone
from bson.errors import InvalidId
from beanie import PydanticObjectId

from app.domain.notification.repository.notification import (
    NotificationRepository,
    PAGE_SIZE,
    UNREAD_COUNT_CAP,
)
from app.domain.notification.model.notification import (
    Notification,
    NotificationType,
    TargetType,
    COMMENT_PREVIEW_MAX_LENGTH,
)
from app.domain.notification.service.exception import NotificationNotFoundError
from app.domain.notification.dto.notification import (
    NotificationData,
    NotificationListData,
)
from app.core.logger import get_logger


logger = get_logger("notification.service")


class NotificationService:
    def __init__(self):
        self.repo = NotificationRepository()


    # ──────────────────── Fan-out (피드 좋아요) ────────────────────

    async def notify_feed_like(
        self,
        *,
        recipient_id: str,
        actor_id: str,
        actor_name: str,
        actor_profile_image_url: Optional[str],
        post_id: str,
        post_preview: Optional[str],
    ) -> None:
        """피드 좋아요 알림 fan-out — RDB 트랜잭션 밖에서 호출.

        본인→본인 좋아요는 skip. `uq_notification_dedup` 으로 같은 (recipient, actor,
        FEED_LIKE, post_id) 의 display=true 알림이 이미 있으면 멱등 skip.
        """
        if recipient_id == actor_id:
            return
        notif = Notification(
            recipient_id=recipient_id,
            actor_id=actor_id,
            type=NotificationType.FEED_LIKE,
            target_type=TargetType.FEED_POST,
            target_id=post_id,
            actor_name=actor_name,
            actor_profile_image_url=actor_profile_image_url,
            target_preview=post_preview,
        )
        await self._safe_insert(notif)


    # ──────────────────── Fan-out (피드 댓글) ────────────────────

    async def notify_feed_comment(
        self,
        *,
        recipient_id: str,
        actor_id: str,
        actor_name: str,
        actor_profile_image_url: Optional[str],
        post_id: str,
        post_preview: Optional[str],
        comment_id: str,
        comment_content: str,
    ) -> None:
        """피드 댓글 알림 fan-out — `comment_id` 마다 별도 알림 (1:1, 묶음 없음).

        본문은 `COMMENT_PREVIEW_MAX_LENGTH` 자로 잘라 snapshot. `comment_id` 가 매번
        달라 unique 충돌 안 함 — 같은 사람이 여러 댓글 달면 매번 알림.
        """
        if recipient_id == actor_id:
            return
        notif = Notification(
            recipient_id=recipient_id,
            actor_id=actor_id,
            type=NotificationType.FEED_COMMENT,
            target_type=TargetType.FEED_POST,
            target_id=post_id,
            comment_id=comment_id,
            actor_name=actor_name,
            actor_profile_image_url=actor_profile_image_url,
            target_preview=post_preview,
            comment_preview=_truncate_comment(comment_content),
        )
        await self._safe_insert(notif)


    # ──────────────────── Fan-out (트립메이트 좋아요) ────────────────────

    async def notify_tripmate_like(
        self,
        *,
        recipient_id: str,
        actor_id: str,
        actor_name: str,
        actor_profile_image_url: Optional[str],
        post_id: str,
        post_preview: Optional[str],
    ) -> None:
        """트립메이트 좋아요 알림 fan-out. `post_preview` 는 게시글 title 전달 권장."""
        if recipient_id == actor_id:
            return
        notif = Notification(
            recipient_id=recipient_id,
            actor_id=actor_id,
            type=NotificationType.TRIPMATE_LIKE,
            target_type=TargetType.TRIPMATE_POST,
            target_id=post_id,
            actor_name=actor_name,
            actor_profile_image_url=actor_profile_image_url,
            target_preview=post_preview,
        )
        await self._safe_insert(notif)


    # ──────────────────── 알림창 조회 ────────────────────

    async def list_notifications(
        self,
        recipient_id: str,
        cursor: Optional[str] = None,
        mark_as_read: bool = False,
    ) -> NotificationListData:
        """알림창 — display=true 만 시간 역순 페이지네이션.

        cursor 는 ISO 8601 datetime string (마지막 알림의 `created_at`). 잘못된 형식은
        `ValueError` 로 router 에서 400.

        `mark_as_read=True` 면 응답 dto 변환 *후* 미읽음 일괄 읽음 처리 (router 가 첫
        페이지 진입 시점에만 True 로 호출). 응답의 `is_read` 는 read 전 상태 (false) 그대로
        유지하여 클라가 "방금 본 알림" 시각 강조 가능 — DB 는 호출 종료 시점에 read_at
        채워진 상태. Mongo 일시 장애는 swallow (다음 진입에 자연 재시도).
        """
        cursor_dt = None
        if cursor is not None:
            try:
                cursor_dt = datetime.fromisoformat(cursor)
            except ValueError:
                raise ValueError("cursor 형식이 올바르지 않습니다.") from None
            # naive datetime 방어 — 외부 클라가 tz 누락 ISO 를 보낸 경우 UTC 로 가정.
            # 서버 반환 next_cursor 는 항상 tz-aware (created_at = UTC) 라 정상 클라엔 영향 없음.
            if cursor_dt.tzinfo is None:
                cursor_dt = cursor_dt.replace(tzinfo=timezone.utc)

        notifs = await self.repo.find_by_recipient(
            recipient_id=recipient_id, cursor=cursor_dt, limit=PAGE_SIZE,
        )
        has_more = len(notifs) > PAGE_SIZE
        notifs = notifs[:PAGE_SIZE]
        next_cursor = (
            notifs[-1].created_at.isoformat() if has_more and notifs else None
        )
        result = NotificationListData(
            notifications=[self._to_dto(n) for n in notifs],
            next_cursor=next_cursor,
        )

        if mark_as_read:
            # dto 변환 후에 update — 응답 is_read 는 read 전 상태 유지.
            try:
                modified = await self.repo.mark_all_read(recipient_id)
                if modified > 0:
                    logger.info(
                        "알림 자동 읽음 처리 (recipient_id={}, count={})",
                        recipient_id, modified,
                    )
            except Exception as e:
                logger.warning(
                    "알림 자동 읽음 처리 실패 (recipient_id={}, error={})",
                    recipient_id, e,
                )

        return result


    async def count_unread(self, recipient_id: str) -> int:
        """미읽음 뱃지 카운트 — 999+ 캡 적용된 값 반환."""
        raw = await self.repo.count_unread(recipient_id, cap=UNREAD_COUNT_CAP)
        return min(raw, UNREAD_COUNT_CAP)


    # ──────────────────── X 버튼 ────────────────────

    async def hide_notification(
        self, recipient_id: str, notification_id: str,
    ) -> None:
        """알림 숨기기 — 본인 소유만. atomic update 로 권한 검증.

        잘못된 ID 형식 / 미존재 / 다른 유저 소유 / 이미 hide 된 알림 모두
        `NotificationNotFoundError` 로 일원화 (정보 누출 회피).
        """
        try:
            oid = PydanticObjectId(notification_id)
        except (InvalidId, TypeError, ValueError):
            raise NotificationNotFoundError("존재하지 않는 알림입니다.") from None

        modified = await self.repo.hide(oid, recipient_id)
        if not modified:
            raise NotificationNotFoundError("존재하지 않는 알림입니다.")
        logger.info("알림 hide (recipient_id={}, notification_id={})", recipient_id, notification_id)


    # ──────────────────── Cascade ────────────────────

    async def cascade_post_deleted(
        self, target_type: TargetType, target_id: str,
    ) -> int:
        """게시물 삭제 시 호출 — 관련 알림 일괄 hard delete. 삭제된 row 수 반환."""
        deleted = await self.repo.delete_by_target(target_type, target_id)
        if deleted > 0:
            logger.info(
                "알림 cascade post_deleted (target_type={}, target_id={}, deleted={})",
                target_type.value, target_id, deleted,
            )
        return deleted


    async def cascade_comment_deleted(self, comment_id: str) -> int:
        """댓글 삭제 시 호출 — 매칭 알림 hard delete."""
        deleted = await self.repo.delete_by_comment(comment_id)
        if deleted > 0:
            logger.info(
                "알림 cascade comment_deleted (comment_id={}, deleted={})",
                comment_id, deleted,
            )
        return deleted


    async def cascade_user_withdrawn(self, user_id: str) -> int:
        """유저 탈퇴 시 호출 — recipient/actor 어느 쪽이든 매칭되는 알림 hard delete."""
        deleted = await self.repo.delete_by_user(user_id)
        if deleted > 0:
            logger.info(
                "알림 cascade user_withdrawn (user_id={}, deleted={})",
                user_id, deleted,
            )
        return deleted


    # ──────────────────── 내부 유틸 ────────────────────

    async def _safe_insert(self, notif: Notification) -> None:
        """fan-out 공통 insert — DuplicateKeyError 멱등 skip, 그 외는 로그만 + 응답 정상.

        RDB 트랜잭션과 분리되어 best-effort 보장. Mongo 일시 장애 시 알림 1건 누락 가능 —
        outbox 패턴은 Phase 2.
        """
        try:
            await self.repo.insert(notif)
        except DuplicateKeyError:
            # 같은 (recipient, actor, type, target, comment) 의 display=true 알림 이미 존재 — 멱등
            return
        except Exception as e:
            logger.warning(
                "알림 fan-out 실패 (type={}, recipient_id={}, target_id={}, error={})",
                notif.type.value, notif.recipient_id, notif.target_id, e,
            )


    @staticmethod
    def _to_dto(n: Notification) -> NotificationData:
        return NotificationData(
            notification_id=str(n.id),
            type=n.type,
            actor_id=n.actor_id,
            actor_name=n.actor_name,
            actor_profile_image_url=n.actor_profile_image_url,
            target_type=n.target_type,
            target_id=n.target_id,
            comment_id=n.comment_id,
            target_preview=n.target_preview,
            comment_preview=n.comment_preview,
            is_read=n.read_at is not None,
            created_at=n.created_at,
        )


def _truncate_comment(content: str) -> str:
    """댓글 본문 snapshot — `COMMENT_PREVIEW_MAX_LENGTH` 자로 자르고 길면 ellipsis."""
    if len(content) <= COMMENT_PREVIEW_MAX_LENGTH:
        return content
    return content[:COMMENT_PREVIEW_MAX_LENGTH] + "…"
