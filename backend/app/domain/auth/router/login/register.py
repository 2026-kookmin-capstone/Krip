from fastapi import APIRouter, HTTPException, Request, Depends
from dependency_injector.wiring import Provide, inject

from app.domain.auth.service.register import RegisterService
from app.domain.auth.schema.register import RegisterRequest
from app.core.logger import get_logger
from app.container import Container


router = APIRouter(prefix="/register", tags=["회원가입"])
logger = get_logger("auth.register")


@router.post("")
@inject
async def register(
    request: Request,
    user_inform: RegisterRequest,
    register_service: RegisterService = Depends(Provide[Container.register_service]),
):
    """2차 회원가입 - 유저 상세 정보 및 여행 스타일 등록"""
    user_id: str = request.state.user_id

    try:
        await register_service.register_detail(
            user_id=user_id,
            email=user_inform.email,
            user_name=user_inform.user_name,
            phone_number=user_inform.phone_number,
            age=user_inform.age,
            gender=user_inform.gender,
            travel_styles=user_inform.travel_styles,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))

    logger.info(f"2차 회원가입 완료: {user_id} / {user_inform.email}")
    return {"message": "회원가입이 완료되었습니다."}
