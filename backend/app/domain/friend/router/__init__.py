from fastapi import APIRouter

from app.domain.friend.router import friendship
from app.domain.friend.router import user_block
from app.domain.friend.router import detail
from app.domain.friend.router import search
from app.domain.friend.router import search_history


friend_router = APIRouter(prefix="/friend")
friend_router.include_router(friendship.router)
friend_router.include_router(user_block.router)
friend_router.include_router(detail.router)
friend_router.include_router(search.router)
friend_router.include_router(search_history.router)
