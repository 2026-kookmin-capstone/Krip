from fastapi import APIRouter

from app.domain.feed.router import feed_post


feed_router = APIRouter(prefix="/feed")
feed_router.include_router(feed_post.router)
