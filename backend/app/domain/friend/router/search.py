from typing import Optional
from fastapi import APIRouter, HTTPException, Request, Depends, Query
from dependency_injector.wiring import Provide, inject

from app.domain.friend.service.search import FriendSearchService
from app.domain.friend.schema.search import (
    FriendSearchItemResponse,
    FriendSearchListResponse,
)
from app.container import Container


router = APIRouter(prefix="/search", tags=["친구 추가 화면 유저 검색"])


@router.get("")
@inject
async def search_users(
    request: Request,
    keyword: str = Query(..., min_length=1, description="검색 키워드 (user_name / user_id 부분일치)"),
    cursor: Optional[str] = Query(None, description="다음 페이지 커서 (user_id)"),
    service: FriendSearchService = Depends(Provide[Container.friend_search_service]),
) -> FriendSearchListResponse:
    """이름 또는 user_id 로 친구 추가 후보 유저 검색 (30개씩 커서 페이지네이션)."""
    viewer_id: str = request.state.user_id

    try:
        result = await service.search(viewer_id=viewer_id, keyword=keyword, cursor=cursor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return _to_list_response(result)


# ──────────────────── 내부 유틸 ────────────────────

def _to_item_response(dto) -> FriendSearchItemResponse:
    return FriendSearchItemResponse(
        user_id=dto.user_id,
        user_name=dto.user_name,
        profile_image_url=dto.profile_image_url,
        nationality=dto.nationality,
        travel_styles=dto.travel_styles,
        friendship_status=dto.friendship_status,
        is_requester=dto.is_requester,
        i_blocked_peer=dto.i_blocked_peer,
    )


def _to_list_response(dto) -> FriendSearchListResponse:
    return FriendSearchListResponse(
        items=[_to_item_response(item) for item in dto.items],
        next_cursor=dto.next_cursor,
    )
