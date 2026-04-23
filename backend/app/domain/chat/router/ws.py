"""채팅 WebSocket 엔드포인트 — `/ws/chat`.

WS 업그레이드 핸드셰이크는 `BaseHTTPMiddleware` 를 거치지 않으므로 인증을
**이 모듈 내부에서 직접** 수행한다 (Origin 화이트리스트 + JWT 쿠키).

연결 플로우
    1. Origin 헤더 화이트리스트 검증 → 실패 시 close(4403)
    2. 쿠키 JWT 검증 → 실패 시 close(4001)
    3. WS accept
    4. SessionService.create_session — Redis 3키 + 세션 한도 체크
    5. WS 컨텍스트 심기 (session_id / user_id / subscribed_rooms)
    6. FanoutService.register_session + 방 목록 register_ws_to_room
    7. `connected` 이벤트 송신
    8. heartbeat 백그라운드 태스크 기동
    9. op 수신 루프 (매 op 진입 시 `session_exists` 체크 — revoke 감지)
    10. 종료 시: unregister_ws → Redis 정리 → WS close
"""
from pydantic import TypeAdapter, ValidationError
import jwt
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from dependency_injector.wiring import Provide, inject
import asyncio

from app.domain.chat.schema.ws_event import ClientRequest, ReadOp, RefreshOp, SendOp
from app.domain.chat.service.message import MessageService
from app.domain.chat.service.exception import ChatRoomNotFoundError, UpstreamError
from app.domain.chat.service.fanout import FanoutService
from app.domain.chat.service.message_history import MessageHistoryService
from app.domain.chat.service.room import RoomService
from app.domain.chat.service.session import SessionService
from app.config.setting import settings
from app.container import Container
from app.core.logger import get_logger


router = APIRouter()
logger = get_logger("chat.ws")


# ──────────────────── 상수 ────────────────────

HEARTBEAT_INTERVAL = 30       # Redis TTL 연장 주기 (초)

# WS close codes
CLOSE_AUTH_EXPIRED = 4001
CLOSE_FORBIDDEN_ORIGIN = 4403
CLOSE_SERVICE_RESTART = 1012


# Pydantic discriminated union 어댑터는 모듈 레벨에서 1회만 생성
_ClientRequestAdapter = TypeAdapter(ClientRequest)


# ──────────────────── 메인 엔드포인트 ────────────────────

@router.websocket("/chat")
@inject
async def ws_chat(
    websocket: WebSocket,
    fanout: FanoutService = Depends(Provide[Container.fanout_service]),
    session_svc: SessionService = Depends(Provide[Container.session_service]),
    room_svc: RoomService = Depends(Provide[Container.room_service]),
    chat_svc: MessageService = Depends(Provide[Container.message_service]),
    history_svc: MessageHistoryService = Depends(Provide[Container.message_history_service]),
) -> None:
    # 1. Origin 검증
    origin = websocket.headers.get("origin")
    if not _is_allowed_origin(origin):
        logger.warning("WS 연결 거부 — 허용되지 않은 Origin: {}", origin)
        await websocket.close(code=CLOSE_FORBIDDEN_ORIGIN)
        return

    # 2. JWT 쿠키 검증
    auth = _verify_cookie_jwt(websocket)
    if auth is None:
        await websocket.close(code=CLOSE_AUTH_EXPIRED)
        return
    user_id, token_jti = auth

    # 3. 업그레이드 수락
    await websocket.accept()

    # 4. Redis 세션 등록 + 한도 체크
    try:
        session_id = await session_svc.create_session(user_id, token_jti)
    except Exception as e:
        logger.exception("세션 생성 실패: user_id={}, err={}", user_id, e)
        await websocket.send_json({"type": "server_error", "reason": "session_create_failed"})
        await websocket.close(code=CLOSE_SERVICE_RESTART)
        return

    # 5. WS 컨텍스트 심기 (FanoutService duck typing 전제)
    websocket.session_id = session_id  # type: ignore[attr-defined]
    websocket.user_id = user_id        # type: ignore[attr-defined]
    websocket.subscribed_rooms = set()  # type: ignore[attr-defined]

    # 6. 세션/방 등록
    fanout.register_session(websocket)
    try:
        room_ids = await room_svc.list_user_room_ids(user_id)
    except Exception as e:
        logger.exception("방 목록 로드 실패: user_id={}, err={}", user_id, e)
        room_ids = []
    for rid in room_ids:
        fanout.register_ws_to_room(websocket, rid)

    # 7. connected 이벤트 — 클라가 session_id 를 수신해 향후 비교/로깅에 사용
    await websocket.send_json({"type": "connected", "session_id": session_id})

    # 7-a. unread 초기 동기화 — Redis 현재값 그대로 push
    #      Redis 가 비어있으면 빈 dict → Phase 3 에서 `recover_unread_for_user` 백그라운드
    #      복구를 이 자리에 연결 예정.
    try:
        counts = await history_svc.get_unread_counts(user_id)
        if counts:
            await websocket.send_json({"type": "unread_synced", "counts": counts})
    except Exception as e:
        logger.warning("unread 동기화 실패 (무시하고 진행): user_id={}, err={}", user_id, e)

    # 8. heartbeat 백그라운드 태스크
    heartbeat_task = asyncio.create_task(
        _heartbeat_loop(session_svc, session_id, user_id),
        name=f"chat-hb-{session_id}",
    )

    # 9. op 수신 루프
    try:
        await _receive_loop(
            websocket=websocket,
            session_id=session_id,
            user_id=user_id,
            session_svc=session_svc,
            chat_svc=chat_svc,
            room_svc=room_svc,
        )
    except WebSocketDisconnect:
        logger.debug("WS 정상 종료: session_id={}", session_id)
    except Exception as e:
        logger.exception("WS 수신 루프 예외: session_id={}, err={}", session_id, e)
    finally:
        # 10. 종료 순서: ① 로컬 dict 먼저 → ② heartbeat 정리 대기 → ③ Redis 정리
        fanout.unregister_ws(websocket)

        # heartbeat task 를 cancel 만 하고 반환하면 pending 상태로 GC 되어
        # "Task was destroyed but it is pending!" 경고 노이즈 + 리소스 누수 위험.
        # gather(return_exceptions=True) 로 CancelledError 소화까지 기다림 (bounded).
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)

        try:
            await session_svc.terminate_session(session_id, user_id)
        except Exception as e:
            logger.warning("세션 종료 실패 (무시): session_id={}, err={}", session_id, e)


# ──────────────────── 인증 ────────────────────

def _is_allowed_origin(origin: str | None) -> bool:
    """CORS 설정과 동일한 Origin 화이트리스트"""
    if origin is None:
        return False
    allowed = {settings.FRONTEND_URL, settings.LOCAL_FRONTEND_URL}
    return origin in allowed


def _verify_cookie_jwt(websocket: WebSocket) -> tuple[str, str] | None:
    """쿠키의 JWT 를 검증해 (user_id, token_jti) 반환. 실패 시 None.

    token_jti 는 JWT `jti` claim 이 없으면 token 앞 32자를 fallback 으로 사용 —
    이는 SessionService 가 `sess:{sid}.token_jti` 에 기록만 하고 현재는 비교하지 않기
    때문. refresh 시점에 같은 로직으로 비교하면 일관성 유지.
    """
    token = websocket.cookies.get(settings.USER_LOGIN_COOKIE_NAME)
    if not token:
        return None
    try:
        payload = jwt.decode(
            token,
            settings.USER_LOGIN_JWT_SECRET_KEY,
            algorithms=[settings.USER_LOGIN_JWT_ALGORITHM],
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        return None

    user_id = payload.get("user_id")
    if not user_id:
        return None
    token_jti = payload.get("jti") or token[:32]
    return str(user_id), str(token_jti)


# ──────────────────── op 수신 루프 ────────────────────

async def _receive_loop(
    *,
    websocket: WebSocket,
    session_id: str,
    user_id: str,
    session_svc: SessionService,
    chat_svc: MessageService,
    room_svc: RoomService,
) -> None:
    """op 디스패처. 매 op 진입 시 Redis 에서 세션 유효성 확인."""
    while True:
        raw = await websocket.receive_json()

        # 매 op 진입 시 revoke 감지 (§3.4)
        if not await session_svc.session_exists(session_id):
            await websocket.send_json({"type": "auth_expired"})
            await websocket.close(code=CLOSE_AUTH_EXPIRED)
            return

        # op 파싱
        try:
            req = _ClientRequestAdapter.validate_python(raw)
        except ValidationError as e:
            first_err = e.errors()[0] if e.errors() else {}
            await websocket.send_json({
                "type": "server_error",
                "reason": f"invalid op: {first_err.get('msg', 'validation failed')}",
            })
            continue

        # 분기 처리
        try:
            if isinstance(req, SendOp):
                await _handle_send(
                    websocket=websocket,
                    session_id=session_id,
                    user_id=user_id,
                    chat_svc=chat_svc,
                    req=req,
                )
            elif isinstance(req, RefreshOp):
                await _handle_refresh(
                    websocket=websocket,
                    session_id=session_id,
                    user_id=user_id,
                    session_svc=session_svc,
                    req=req,
                )
            elif isinstance(req, ReadOp):
                await _handle_read(
                    websocket=websocket,
                    session_id=session_id,
                    user_id=user_id,
                    room_svc=room_svc,
                    req=req,
                )
        except PermissionError as e:
            # read op 는 `read_failed` 이벤트로 실패 사유를 전달 — 다른 op 는
            # `server_error` 규약 유지.
            if isinstance(req, ReadOp):
                await websocket.send_json({
                    "type": "read_failed", "room_id": req.room_id, "reason": str(e),
                })
            else:
                await websocket.send_json({"type": "server_error", "reason": str(e)})
        except ValueError as e:
            if isinstance(req, ReadOp):
                await websocket.send_json({
                    "type": "read_failed", "room_id": req.room_id, "reason": str(e),
                })
            else:
                await websocket.send_json({"type": "server_error", "reason": str(e)})
        except ChatRoomNotFoundError as e:
            if isinstance(req, ReadOp):
                await websocket.send_json({
                    "type": "read_failed", "room_id": req.room_id, "reason": str(e),
                })
            else:
                await websocket.send_json({"type": "server_error", "reason": str(e)})
        except UpstreamError as e:
            # 외부 저장소 지속 실패 — 연결은 유지, 클라가 재시도 가능
            await websocket.send_json({"type": "server_error", "reason": str(e)})


async def _handle_send(
    *,
    websocket: WebSocket,
    session_id: str,
    user_id: str,
    chat_svc: MessageService,
    req: SendOp,
) -> None:
    """`op=send` — MessageService.send_message 실행 후 ACK 직송."""
    ack = await chat_svc.send_message(
        sender_user_id=user_id,
        sender_session_id=session_id,
        room_id=req.room_id,
        client_msg_id=req.client_msg_id,
        msg_type=req.type,
        content=req.content,
    )
    await websocket.send_json({
        "type": "message.sent",
        "client_msg_id": ack.client_msg_id,
        "message_id": ack.message_id,
        "server_seq": ack.server_seq,
        "created_at": ack.created_at.isoformat(),
    })


async def _handle_refresh(
    *,
    websocket: WebSocket,
    session_id: str,
    user_id: str,
    session_svc: SessionService,
    req: RefreshOp,
) -> None:
    """`op=refresh` — JWT 재검증 후 `sess:{sid}.token_jti` 갱신. session_id 는 유지."""
    try:
        payload = jwt.decode(
            req.token,
            settings.USER_LOGIN_JWT_SECRET_KEY,
            algorithms=[settings.USER_LOGIN_JWT_ALGORITHM],
        )
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        await websocket.send_json({"type": "auth_expired"})
        await websocket.close(code=CLOSE_AUTH_EXPIRED)
        return

    if payload.get("user_id") != user_id:
        await websocket.send_json({"type": "auth_expired"})
        await websocket.close(code=CLOSE_AUTH_EXPIRED)
        return

    new_jti = payload.get("jti") or req.token[:32]
    await session_svc.update_token_jti(session_id, new_jti)


async def _handle_read(
    *,
    websocket: WebSocket,
    session_id: str,
    user_id: str,
    room_svc: RoomService,
    req: ReadOp,
) -> None:
    """`op=read` — RoomService.mark_read 로 포인터 갱신 + ack/fan-out.

    `mark_read` 내부에서 `read_ack` 발신 세션 직송 + `read` 이벤트 방 브로드캐스트까지
    수행하므로 여기서는 별도 추가 전송이 없다. 실패 시 예외는 `_receive_loop` 의
    분기에서 `read_failed` 로 변환된다.
    """
    await room_svc.mark_read(
        me_id=user_id,
        me_session_id=session_id,
        room_id=req.room_id,
        up_to_server_seq=req.up_to_server_seq,
    )


# ──────────────────── heartbeat ────────────────────

async def _heartbeat_loop(
    session_svc: SessionService,
    session_id: str,
    user_id: str,
) -> None:
    """`HEARTBEAT_INTERVAL` 초마다 Redis TTL 연장. 메인 루프 종료 시 cancel 됨."""
    try:
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            try:
                await session_svc.heartbeat(session_id, user_id)
            except Exception as e:
                logger.warning(
                    "heartbeat 실패 (계속 진행): session_id={}, err={}", session_id, e,
                )
    except asyncio.CancelledError:
        raise
