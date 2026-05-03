from typing import Optional
from firebase_admin.exceptions import FirebaseError
from firebase_admin import messaging
import asyncio

from app.core.fcm import get_fcm_app
from app.core.logger import get_logger
from app.domain.notification.repository.fcm_token import FcmTokenRepository
from app.domain.notification.model.fcm_token import FcmToken
from app.domain.notification.dto.fcm_token import FcmTokenData
from app.database.session import UnitOfWork, transactional


logger = get_logger("fcm_service")


class FcmService:
    """FCM 토큰 등록/해제 + 푸시 발송 서비스.

    - 발송은 user_id 기준 → 해당 유저의 모든 디바이스에 multicast 1회 호출.
    - 응답에서 `UnregisteredError`(앱 삭제 또는 토큰 만료) 토큰은 즉시 DB 에서 정리.
    - `firebase_admin.messaging` 은 동기 SDK 라 `asyncio.to_thread` 로 감싸
      이벤트 루프를 막지 않는다.
    - FCM 발송이 외부 네트워크 호출이라 트랜잭션이 일시적으로 길어질 수 있으나,
      성공한 토큰과 만료 토큰 정리를 같은 트랜잭션에서 원자적으로 마무리할 수 있어
      `@transactional` 안에서 처리한다.
    """

    def __init__(self, uow: UnitOfWork):
        self.uow = uow


    # ──────────────────── 토큰 등록 / 해제 ────────────────────

    @transactional
    async def register_token(self, *, user_id: str, token: str) -> FcmTokenData:
        """디바이스 토큰 등록.

        - 신규 토큰: 새 row 저장
        - 동일 token 이 다른 user 로 등록되어 있음: owner 만 교체
          (한 디바이스에서 계정 A → B 로 재로그인한 케이스)
        - 동일 (user, token) 재등록: no-op
        """
        repo = FcmTokenRepository(self._session)

        existing = await repo.find_by_token(token)
        if existing is None:
            saved = await repo.save(FcmToken(user_id=user_id, token=token))
            return self._to_dto(saved)

        if existing.user_id != user_id:
            existing.user_id = user_id
            updated = await repo.update(existing)
            return self._to_dto(updated)

        return self._to_dto(existing)


    @transactional
    async def unregister_token(self, *, user_id: str, token: str) -> None:
        """디바이스 토큰 해제 — 클라이언트 명시적 로그아웃 시점.

        본인 소유 토큰만 삭제 가능. 존재하지 않거나 이미 다른 사용자 소유로
        넘어간 토큰을 넘겨도 idempotent 하게 동작 (조용히 종료).
        """
        repo = FcmTokenRepository(self._session)
        existing = await repo.find_by_token(token)
        if existing is None:
            return
        if existing.user_id != user_id:
            return
        await repo.delete(existing)


    # ──────────────────── 채팅 푸시 ────────────────────

    @transactional
    async def send_chat_push(
        self,
        *,
        user_id: str,
        chat_room_id: str,
        sender_id: str,
        title: str,
        body: str,
    ) -> int:
        """채팅 새 메시지 푸시 — 클라이언트가 알림 탭 시 방으로 라우팅할 수 있도록
        `type / chatRoomId / senderId / url` 데이터 페이로드 포함.

        FCM 규격상 data 값은 모두 string. 호출자는 이미 string 화된 ID 를 넘긴다.
        반환: 발송 성공한 디바이스 수.
        """
        data = {
            "type": "chat",
            "chatRoomId": chat_room_id,
            "senderId": sender_id,
            "url": f"/chat/{chat_room_id}",
        }
        return await self._send_to_user(
            user_id=user_id, title=title, body=body, data=data,
        )


    # ──────────────────── 내부 ────────────────────

    async def _send_to_user(
        self,
        *,
        user_id: str,
        title: str,
        body: str,
        data: Optional[dict[str, str]] = None,
    ) -> int:
        """user_id 의 모든 토큰으로 multicast + 만료 토큰 자동 정리.

        반드시 `@transactional` 컨텍스트 안에서 호출해야 한다 (self._session 사용).
        """
        repo = FcmTokenRepository(self._session)
        rows = await repo.find_by_user_id(user_id)
        if not rows:
            return 0

        tokens = [r.token for r in rows]
        multicast = messaging.MulticastMessage(
            tokens=tokens,
            notification=messaging.Notification(title=title, body=body),
            data=data,
        )

        try:
            batch = await asyncio.to_thread(
                messaging.send_each_for_multicast, multicast, app=get_fcm_app(),
            )
        except FirebaseError as e:
            # 글로벌 실패 (인증/네트워크) — 토큰 정리 없이 0 반환. 비즈는 계속.
            logger.warning("FCM multicast 실패 user_id={} error={}", user_id, e)
            return 0

        # 토큰별 응답 검사 — 앱 삭제로 인한 UnregisteredError 면 즉시 DB 정리.
        invalid_tokens: list[str] = []
        for token, resp in zip(tokens, batch.responses):
            if resp.success:
                continue
            err = resp.exception
            if isinstance(err, messaging.UnregisteredError):
                invalid_tokens.append(token)
            else:
                logger.warning(
                    "FCM 발송 실패 user_id={} token_prefix={} error={}",
                    user_id, token[:16], err,
                )

        if invalid_tokens:
            await repo.delete_by_tokens(invalid_tokens)
            logger.info(
                "FCM 만료 토큰 정리 user_id={} count={}",
                user_id, len(invalid_tokens),
            )

        return batch.success_count


    # ──────────────────── 변환 ────────────────────

    @staticmethod
    def _to_dto(fcm_token: FcmToken) -> FcmTokenData:
        return FcmTokenData(
            fcm_token_id=fcm_token.fcm_token_id,
            created_at=fcm_token.created_at,
        )
