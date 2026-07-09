from fastapi import APIRouter

from app.domain.friend.router import detail, friendship, search, search_history, user_block


friend_router = APIRouter(prefix="/friend")
friend_router.include_router(friendship.router)
friend_router.include_router(user_block.router)
friend_router.include_router(detail.router)
friend_router.include_router(search.router)
friend_router.include_router(search_history.router)
