from fastapi import APIRouter, HTTPException, Request, Depends
from fastapi.responses import JSONResponse
from dependency_injector.wiring import Provide, inject

from app.domain.auth.service.withdraw import WithdrawService
from app.core.logger import get_logger
from app.config.setting import settings
from app.container import Container


router = APIRouter(prefix="/withdraw", tags=["회원 탈퇴"])
logger = get_logger("auth.withdraw")


@router.delete("")
@inject
async def withdraw(
    request: Request,
    withdraw_service: WithdrawService = Depends(Provide[Container.withdraw_service]),
) -> JSONResponse:
    """회원 탈퇴 — 유저 관련 모든 데이터 영구 삭제"""
    user_id: str = request.state.user_id

    try:
        await withdraw_service.withdraw(user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    response = JSONResponse(content={"message": "회원 탈퇴가 완료되었습니다."})
    response.delete_cookie(
        key=settings.USER_LOGIN_COOKIE_NAME,
        httponly=True,
        secure=True,
        samesite="none",
        path="/",
    )

    logger.info("회원 탈퇴 완료 (user_id={})", user_id)
    return response
