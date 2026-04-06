from fastapi import APIRouter, HTTPException, Request, Depends
from dependency_injector.wiring import Provide, inject

from app.domain.auth.service.profile import ProfileService
from app.domain.auth.schema.profile import ProfileResponse
from app.core.logger import get_logger
from app.container import Container


router = APIRouter(prefix="/profile", tags=["프로필"])
logger = get_logger("auth.profile")


@router.get("/me")
@inject
async def get_my_profile(
    request: Request,
    profile_service: ProfileService = Depends(Provide[Container.profile_service]),
) -> ProfileResponse:
    """내 프로필 조회"""
    user_id: str = request.state.user_id

    try:
        profile = await profile_service.get_my_profile(user_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return ProfileResponse(
        user_id=profile.user_id,
        auth_provider=profile.auth_provider.value,
        status=profile.status.value,
        email=profile.email,
        user_name=profile.user_name,
        phone_number=profile.phone_number,
        age=profile.age,
        gender=profile.gender,
        travel_styles=profile.travel_styles,
    )
