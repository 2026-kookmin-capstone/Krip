from fastapi import APIRouter

from app.domain.friend.router import friendship
from app.domain.friend.router import user_block


friend_router = APIRouter(prefix="/friend")
friend_router.include_router(friendship.router)
friend_router.include_router(user_block.router)
