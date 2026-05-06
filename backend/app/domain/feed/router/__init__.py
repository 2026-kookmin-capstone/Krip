from fastapi import APIRouter

from app.domain.feed.router import feed_post
from app.domain.feed.router import feed_user


feed_router = APIRouter(prefix="/feed")
feed_router.include_router(feed_post.router)
feed_router.include_router(feed_user.router)
