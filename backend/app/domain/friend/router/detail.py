from fastapi import APIRouter, HTTPException, Request, Depends
from dependency_injector.wiring import Provide, inject

from app.domain.friend.service.friend_detail import FriendDetailService, UserNotFoundError
from app.domain.friend.schema.friend_detail import FriendDetailResponse
from app.container import Container


router = APIRouter(prefix="/detail", tags=["친구 상세 조회"])


@router.get("/{user_id}")
@inject
async def get_friend_detail(
    request: Request,
    user_id: str,
    service: FriendDetailService = Depends(Provide[Container.friend_detail_service]),
) -> FriendDetailResponse:
    """상대 유저 프로필 + 내 기준 친구 관계 상태 조회.
    """
    viewer_id: str = request.state.user_id

    try:
        result = await service.get_friend_detail(viewer_id=viewer_id, peer_id=user_id)
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return FriendDetailResponse(
        user_id=result.user_id,
        user_name=result.user_name,
        age=result.age,
        gender=result.gender,
        nationality=result.nationality,
        travel_styles=result.travel_styles,
        friendship_id=result.friendship_id,
        friendship_status=result.friendship_status,
        is_requester=result.is_requester,
        i_blocked_peer=result.i_blocked_peer,
    )
