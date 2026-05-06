"""피드 게시물 좋아요 라우터.

엔드포인트:
    POST   /feed/posts/{post_id}/like   — 좋아요 추가
    DELETE /feed/posts/{post_id}/like   — 좋아요 취소
    GET    /feed/posts/{post_id}/likes  — 좋아요 누른 유저 ID 목록 (최신순)

에러 매핑:
    FeedNotFoundError       → 404 (미존재 또는 visibility 미충족 — 정보 누출 회피)
    FeedBlockedError        → 403 (PermissionError 하위 — except PermissionError 로 catch)
    ValueError (중복/미존재) → 400 (`이미 좋아요`, `좋아요 안 누름`)

본인 글에 본인이 좋아요 가능 (인스타 동치). 같은 (user, post) 동시 POST race 는 service
레이어가 `IntegrityError` 를 catch 해 ValueError 로 변환 → 일반 중복 케이스와 동일하게
400 응답 (라우터엔 SQLAlchemy 의존성 누출 없음).
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from dependency_injector.wiring import Provide, inject

from app.domain.feed.service.feed_post_like import FeedPostLikeService
from app.domain.feed.service.exception import FeedNotFoundError
from app.domain.feed.schema.feed_post_like import LikeResponse, LikedUsersResponse
from app.container import Container


router = APIRouter(tags=["피드 좋아요"])


# ──────────────────── 추가 ────────────────────

@router.post("/posts/{post_id}/like", status_code=201)
@inject
async def add_like(
    request: Request,
    post_id: str,
    like_service: FeedPostLikeService = Depends(Provide[Container.feed_post_like_service]),
) -> LikeResponse:
    """게시물 좋아요 추가."""
    user_id: str = request.state.user_id
    try:
        like_count = await like_service.add_like(user_id=user_id, post_id=post_id)
    except FeedNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return LikeResponse(post_id=post_id, like_count=like_count)


# ──────────────────── 취소 ────────────────────

@router.delete("/posts/{post_id}/like")
@inject
async def remove_like(
    request: Request,
    post_id: str,
    like_service: FeedPostLikeService = Depends(Provide[Container.feed_post_like_service]),
) -> LikeResponse:
    """게시물 좋아요 취소."""
    user_id: str = request.state.user_id
    try:
        like_count = await like_service.remove_like(user_id=user_id, post_id=post_id)
    except FeedNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return LikeResponse(post_id=post_id, like_count=like_count)


# ──────────────────── 좋아요 누른 유저 목록 ────────────────────

@router.get("/posts/{post_id}/likes")
@inject
async def get_liked_users(
    request: Request,
    post_id: str,
    like_service: FeedPostLikeService = Depends(Provide[Container.feed_post_like_service]),
) -> LikedUsersResponse:
    """좋아요 누른 유저 ID 목록 — 최신순. 프로필 정보는 후속 batch 조회로 분리."""
    viewer_id: str = request.state.user_id
    try:
        user_ids = await like_service.get_liked_user_ids(
            viewer_id=viewer_id, post_id=post_id,
        )
    except FeedNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))

    return LikedUsersResponse(post_id=post_id, user_ids=user_ids)
