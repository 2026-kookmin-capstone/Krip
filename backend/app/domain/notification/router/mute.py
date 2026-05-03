from fastapi import APIRouter, Depends, HTTPException, Request
from dependency_injector.wiring import Provide, inject

from app.schema.common import MessageResponse
from app.domain.notification.service.mute import MuteService
from app.container import Container


router = APIRouter(prefix="/mute", tags=["알림 차단"])


# ──────────────────── 전역 ────────────────────

@router.post("/global")
@inject
async def mute_global(
    request: Request,
    service: MuteService = Depends(Provide[Container.mute_service]),
) -> MessageResponse:
    """전역 알림 차단."""
    user_id: str = request.state.user_id

    try:
        await service.set_global_mute(user_id=user_id, muted=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return MessageResponse(message="모든 알림을 차단했습니다.")


@router.delete("/global")
@inject
async def unmute_global(
    request: Request,
    service: MuteService = Depends(Provide[Container.mute_service]),
) -> MessageResponse:
    """전역 알림 차단 해제."""
    user_id: str = request.state.user_id

    try:
        await service.set_global_mute(user_id=user_id, muted=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return MessageResponse(message="알림 차단을 해제했습니다.")


# ──────────────────── 방별 ────────────────────

@router.post("/rooms/{chat_room_id}")
@inject
async def mute_room(
    request: Request,
    chat_room_id: str,
    service: MuteService = Depends(Provide[Container.mute_service]),
) -> MessageResponse:
    """특정 방의 알림 차단."""
    user_id: str = request.state.user_id

    try:
        await service.set_room_mute(user_id=user_id, chat_room_id=chat_room_id, muted=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return MessageResponse(message="이 방의 알림을 차단했습니다.")


@router.delete("/rooms/{chat_room_id}")
@inject
async def unmute_room(
    request: Request,
    chat_room_id: str,
    service: MuteService = Depends(Provide[Container.mute_service]),
) -> MessageResponse:
    """특정 방의 알림 차단 해제."""
    user_id: str = request.state.user_id

    try:
        await service.set_room_mute(user_id=user_id, chat_room_id=chat_room_id, muted=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return MessageResponse(message="이 방의 알림 차단을 해제했습니다.")
