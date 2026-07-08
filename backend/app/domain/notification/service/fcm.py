"""FCM 토큰 등록/해제 + 채팅 푸시 발송.

채팅 푸시는 fan-out 단위 → 가드/조회/발송/정리를 한 트랜잭션 + 한 multicast 로 묶어 N+1 회피.
firebase_admin SDK 가 동기라 `asyncio.to_thread` 로 감싸 이벤트 루프 비차단.
"""
from firebase_admin.exceptions import FirebaseError
from firebase_admin import messaging
import asyncio

from app.domain.notification.repository.fcm_token import FcmTokenRepository
from app.domain.notification.model.fcm_token import FcmToken
from app.domain.notification.dto.fcm_token import FcmTokenData
from app.domain.chat.repository.chat_member import ChatRoomMemberRepository
from app.domain.auth.repository.user_detail_inform import UserDetailInformRepository
from app.domain.auth.repository.user import UserRepository
from app.database.session import UnitOfWork, transactional
from app.core.logger import get_logger
from app.core.instrumentation import (
    fcm_multicast_devices_inc,
    fcm_multicast_timer,
    fcm_send_inc,
    fcm_token_purged_inc,
)
from app.core.fcm import get_fcm_app


logger = get_logger("fcm_service")


# 발신자 이름 조회 실패 (탈퇴 / detail 결손) 시 fallback.
_DEFAULT_CHAT_PUSH_TITLE = "새 메시지"


class FcmService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow


    @transactional
    async def register_token(self, *, user_id: str, token: str) -> FcmTokenData:
        """디바이스 토큰 등록 — UNIQUE(token) 충돌 시 owner 교체 (재로그인/계정 전환), 동시 등록 race 안전."""
        repo = FcmTokenRepository(self._session)
        saved = await repo.upsert_by_token(user_id=user_id, token=token)
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
    ) -> int:
        """채팅 새 메시지 푸시 — N명 fan-out.

        multicast(네트워크 RTT)는 트랜잭션 밖에서 발송해 커넥션을 점유하지 않는다.
        대상 조회와 만료 토큰 정리만 각각 짧은 트랜잭션으로 감싼다.
        """
        if not user_ids:
            return 0

        collected = await self._collect_push_targets(
            user_ids=user_ids, chat_room_id=chat_room_id, sender_id=sender_id, title=title,
        )
        if collected is None:
            return 0
        tokens, final_title = collected

        multicast = messaging.MulticastMessage(
            tokens=tokens,
            notification=messaging.Notification(title=final_title, body=body),
            data={
                "type": "chat",
                "chatRoomId": chat_room_id,
                "senderId": sender_id,
                "url": f"/chat/{chat_room_id}",
            },
        )

        try:
            async with fcm_multicast_timer("chat"):
                batch = await asyncio.to_thread(
                    messaging.send_each_for_multicast, multicast, app=get_fcm_app(),
                )
        except FirebaseError as e:
            # 글로벌 실패 (인증/네트워크) — 토큰 정리 없이 0. 비즈는 계속.
            fcm_send_inc("chat", "global_failed")
            logger.warning(
                "FCM multicast 실패 chat_room_id={} count={} error={}",
                chat_room_id, len(tokens), e,
            )
            return 0

        fcm_send_inc("chat", "ok")

        success_count = 0
        failed_unregistered = 0
        failed_other = 0
        invalid_tokens: list[str] = []
        for token, resp in zip(tokens, batch.responses):
            if resp.success:
                success_count += 1
                continue
            err = resp.exception
            if isinstance(err, messaging.UnregisteredError):
                failed_unregistered += 1
                invalid_tokens.append(token)
            else:
                failed_other += 1
                logger.warning(
                    "FCM 발송 실패 chat_room_id={} token_prefix={} error={}",
                    chat_room_id, token[:16], err,
                )

        fcm_multicast_devices_inc(
            success=success_count,
            failed_unregistered=failed_unregistered,
            failed_other=failed_other,
        )

        if invalid_tokens:
            await self._purge_invalid_tokens(chat_room_id, invalid_tokens)

        return batch.success_count


    @transactional
    async def _collect_push_targets(
        self,
        *,
        user_ids: list[str],
        chat_room_id: str,
        sender_id: str,
        title: str | None,
    ) -> tuple[list[str], str] | None:
        """가드 체인(방별 → 전역 mute → 토큰) 통과 대상의 토큰 + title 반환. 대상 0이면 None."""
        member_repo = ChatRoomMemberRepository(self._session)
        pushable_in_room = await member_repo.find_pushable_user_ids_in_room(
            chat_room_id, user_ids,
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
