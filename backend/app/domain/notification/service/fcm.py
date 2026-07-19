"""FCM 토큰 등록/해제 + 채팅 푸시 발송.

채팅 푸시는 fan-out 단위 → 가드/조회/발송/정리를 한 트랜잭션 + 한 multicast 로 묶어 N+1 회피.
firebase_admin SDK 가 동기라 `asyncio.to_thread` 로 감싸 이벤트 루프 비차단.
"""
import asyncio
from datetime import datetime

from firebase_admin import messaging
from firebase_admin.exceptions import FirebaseError
from sqlalchemy import text

from app.core.fcm import get_fcm_app
from app.core.instrumentation import (
    fcm_multicast_devices_inc,
    fcm_multicast_timer,
    fcm_send_inc,
    fcm_token_purged_inc,
)
from app.core.logger import get_logger
from app.database.session import UnitOfWork, mongodb, transactional
from app.domain.auth.repository.user import UserRepository
from app.domain.auth.repository.user_detail_inform import UserDetailInformRepository
from app.domain.chat.repository.chat_member import ChatRoomMemberRepository
from app.domain.chat.repository.chat_message import ChatMessageRepository
from app.domain.notification.dto.fcm_token import FcmTokenData
from app.domain.notification.model.fcm_token import FcmToken
from app.domain.notification.repository.fcm_token import FcmTokenRepository


logger = get_logger("fcm_service")


# 발신자 이름 조회 실패 (탈퇴 / detail 결손) 시 fallback.
_DEFAULT_CHAT_PUSH_TITLE = "새 메시지"

# MulticastMessage 의 토큰 상한 (firebase_admin 이 초과 시 ValueError). 이 크기로 청크 분할.
_FCM_MULTICAST_MAX = 500
_PUSH_BODY_PREVIEW_LIMIT = 100

# 유저당 보관할 최대 디바이스 토큰 수 — 초과분은 updated_at 오래된 것부터 정리.
MAX_TOKENS_PER_USER = 10
_FCM_TOKEN_REGISTRATION_LOCK = "fcm-token-registration"


class FcmService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    @transactional
    async def register_token(self, *, user_id: str, token: str) -> FcmTokenData:
        """디바이스 토큰 등록 — UNIQUE(token) 충돌 시 owner 교체 (재로그인/계정 전환), 동시 등록 race 안전."""
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_name, 0))"),
            {"lock_name": _FCM_TOKEN_REGISTRATION_LOCK},
        )
        user_repo = UserRepository(self._session)
        if not await user_repo.lock_if_active(user_id):
            raise PermissionError("비활성 계정은 FCM 토큰을 등록할 수 없습니다.")
        repo = FcmTokenRepository(self._session)
        saved = await repo.upsert_by_token(user_id=user_id, token=token)
        # 유저당 토큰 수 상한 — 무제한 등록으로 인한 테이블 성장 + 푸시 팬아웃 폭증 방지.
        # 방금 upsert 한 토큰은 updated_at 이 최신이라 항상 보존된다.
        await repo.prune_user_tokens_keeping_latest(
            user_id=user_id, keep=MAX_TOKENS_PER_USER,
        )
        return self._to_dto(saved)

    @transactional
    async def unregister_token(self, *, user_id: str, token: str) -> None:
        """본인 소유만 삭제 — 없거나 타인 소유면 0 row, 멱등."""
        repo = FcmTokenRepository(self._session)
        await repo.delete_by_user_token(user_id=user_id, token=token)

    async def send_chat_push(
        self,
        *,
        user_ids: list[str],
        chat_room_id: str,
        sender_id: str,
        body: str,
        title: str | None = None,
        expected_membership_generations: dict[str, datetime] | None = None,
        message_id: str | None = None,
    ) -> int:
        """채팅 새 메시지 푸시 — N명 fan-out.

        활성 계정·멤버십 share lock을 bounded multicast 완료까지 유지해
        withdrawal/leave/kick과 push 전달을 직렬화한다.
        """
        if not user_ids:
            return 0

        success_total, invalid_tokens = await self._send_chat_push_tx(
            user_ids=user_ids,
            chat_room_id=chat_room_id,
            sender_id=sender_id,
            body=body,
            title=title,
            expected_membership_generations=expected_membership_generations,
            message_id=message_id,
        )
        if invalid_tokens:
            try:
                await self._purge_invalid_tokens(chat_room_id, invalid_tokens)
            except Exception as e:
                logger.warning(
                    "FCM 만료 토큰 정리 실패 (무시): chat_room_id={}, error={}",
                    chat_room_id, type(e).__name__,
                )
        return success_total

    @transactional
    async def _send_chat_push_tx(
        self,
        *,
        user_ids: list[str],
        chat_room_id: str,
        sender_id: str,
        body: str,
        title: str | None,
        expected_membership_generations: dict[str, datetime] | None,
        message_id: str | None,
    ) -> tuple[int, list[str]]:
        if message_id is not None:
            current_body = await self._lock_and_resolve_chat_body(
                message_id=message_id, chat_room_id=chat_room_id,
            )
            if current_body is None:
                return 0, []
            body = current_body

        collected = await self._collect_push_targets(
            user_ids=user_ids, chat_room_id=chat_room_id, sender_id=sender_id, title=title,
            expected_membership_generations=expected_membership_generations,
        )
        if collected is None:
            return 0, []
        tokens, final_title = collected

        notification = messaging.Notification(title=final_title, body=body)
        data = {
            "type": "chat",
            "chatRoomId": chat_room_id,
            "senderId": sender_id,
            "url": f"/chat/{chat_room_id}",
        }

        # 토큰이 _FCM_MULTICAST_MAX 를 넘으면 MulticastMessage 생성에서 ValueError 가 나
        # 방 전체 푸시가 조용히 전멸한다 (호출측 catch-all 이 삼킴). 청크로 분할 발송한다.
        success_total = 0
        invalid_tokens: list[str] = []
        for start in range(0, len(tokens), _FCM_MULTICAST_MAX):
            chunk = tokens[start:start + _FCM_MULTICAST_MAX]
            multicast = messaging.MulticastMessage(
                tokens=chunk, notification=notification, data=data,
            )
            send_task = asyncio.create_task(asyncio.to_thread(
                messaging.send_each_for_multicast, multicast, app=get_fcm_app(),
            ))
            cancelled = False
            try:
                async with fcm_multicast_timer("chat"):
                    while True:
                        try:
                            batch = await asyncio.shield(send_task)
                            break
                        except asyncio.CancelledError:
                            if send_task.cancelled():
                                raise
                            cancelled = True
            except FirebaseError as e:
                # 이 청크만 글로벌 실패 (인증/네트워크) — 다음 청크는 계속 시도.
                fcm_send_inc("chat", "global_failed")
                logger.warning(
                    "FCM multicast 실패 chat_room_id={} count={} error={}",
                    chat_room_id, len(chunk), e,
                )
                if cancelled:
                    raise asyncio.CancelledError
                continue
            except Exception as e:
                if cancelled:
                    logger.error(
                        "FCM multicast drain 중 예상 밖 실패: chat_room_id={}, error={}",
                        chat_room_id, e,
                    )
                    raise asyncio.CancelledError from e
                raise

            fcm_send_inc("chat", "ok")
            success_count, chunk_invalid = self._parse_batch(chat_room_id, chunk, batch)
            success_total += success_count
            invalid_tokens.extend(chunk_invalid)
            if cancelled:
                raise asyncio.CancelledError

        return success_total, invalid_tokens

    @transactional
    async def _lock_and_resolve_chat_body(
        self, *, message_id: str, chat_room_id: str,
    ) -> str | None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:lock_name, 0))"),
            {"lock_name": f"chat-message-mutation:{message_id}"},
        )
        if mongodb.database is None:
            raise RuntimeError("MongoDB is not initialized")
        doc = await ChatMessageRepository(mongodb.database).find_by_id(message_id)
        if (
            doc is None
            or doc.get("chat_room_id") != chat_room_id
            or doc.get("deleted_at") is not None
            or not isinstance(doc.get("content"), str)
        ):
            return None
        content = doc["content"]
        return (
            content[:_PUSH_BODY_PREVIEW_LIMIT] + "..."
            if len(content) > _PUSH_BODY_PREVIEW_LIMIT
            else content
        )

    @staticmethod
    def _parse_batch(
        chat_room_id: str, tokens: list[str], batch,
    ) -> tuple[int, list[str]]:
        """multicast 응답 파싱 — (성공 수, 영구 무효 토큰 목록) 반환 + 디바이스 메트릭 기록.

        영구 무효 = UNREGISTERED(앱 삭제) + SENDER_ID_MISMATCH(타 프로젝트 토큰). 둘 다
        재시도해도 절대 성공하지 않으므로 DELETE 대상. 그 외 실패는 일시적일 수 있어 보존.
        """
        success_count = 0
        failed_unregistered = 0
        failed_other = 0
        invalid_tokens: list[str] = []
        for token, resp in zip(tokens, batch.responses):
            if resp.success:
                success_count += 1
                continue
            err = resp.exception
            if isinstance(
                err,
                (messaging.UnregisteredError, messaging.SenderIdMismatchError),
            ):
                failed_unregistered += 1
                invalid_tokens.append(token)
            else:
                failed_other += 1
                logger.bind(chat_room_id=chat_room_id, error=err).warning("FCM 발송 실패")

        fcm_multicast_devices_inc(
            success=success_count,
            failed_unregistered=failed_unregistered,
            failed_other=failed_other,
        )
        return success_count, invalid_tokens

    @transactional
    async def _collect_push_targets(
        self,
        *,
        user_ids: list[str],
        chat_room_id: str,
        sender_id: str,
        title: str | None,
        expected_membership_generations: dict[str, datetime] | None,
    ) -> tuple[list[str], str] | None:
        """가드 체인(방별 → 전역 mute → 토큰) 통과 대상의 토큰 + title 반환. 대상 0이면 None."""
        member_repo = ChatRoomMemberRepository(self._session)
        pushable_in_room = await member_repo.find_pushable_user_ids_in_room(
            chat_room_id, user_ids, expected_membership_generations,
        )
        if not pushable_in_room:
            return None

        user_repo = UserRepository(self._session)
        allowed = await user_repo.find_unmuted_user_ids(list(pushable_in_room))
        if not allowed:
            return None

        token_repo = FcmTokenRepository(self._session)
        rows = await token_repo.find_by_user_ids(list(allowed))
        if not rows:
            return None

        final_title = title if title is not None else (
            await self._resolve_sender_display_name(sender_id)
        )
        return [r.token for r in rows], final_title

    @transactional
    async def _purge_invalid_tokens(self, chat_room_id: str, tokens: list[str]) -> None:
        """UnregisteredError(앱 삭제) 토큰 bulk DELETE."""
        token_repo = FcmTokenRepository(self._session)
        await token_repo.delete_by_tokens(tokens)
        fcm_token_purged_inc(len(tokens))
        logger.info(
            "FCM 만료 토큰 정리 chat_room_id={} count={}",
            chat_room_id, len(tokens),
        )

    async def _resolve_sender_display_name(self, sender_id: str) -> str:
        """발신자 user_id → 푸시 title. 실패 시 기본 문구 fallback (이름 조회 실패가 푸시를 막지 않도록)."""
        try:
            detail_repo = UserDetailInformRepository(self._session)
            detail = await detail_repo.find_by_user_id(sender_id)
        except Exception as e:
            logger.warning(
                "발신자 이름 조회 실패 sender_id={} error={}",
                sender_id, type(e).__name__,
            )
            return _DEFAULT_CHAT_PUSH_TITLE

        if detail is None or not detail.user_name:
            return _DEFAULT_CHAT_PUSH_TITLE
        return detail.user_name

    @staticmethod
    def _to_dto(fcm_token: FcmToken) -> FcmTokenData:
        return FcmTokenData(
            fcm_token_id=fcm_token.fcm_token_id,
            created_at=fcm_token.created_at,
        )
