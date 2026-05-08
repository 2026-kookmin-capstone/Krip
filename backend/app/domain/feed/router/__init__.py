from fastapi import APIRouter

from app.domain.feed.router import feed_post
from app.domain.feed.router import feed_user
from app.domain.feed.router import feed_post_like
from app.domain.feed.router import feed_post_comment
from app.domain.feed.router import feed_popup


feed_router = APIRouter(prefix="/feed")
feed_router.include_router(feed_post.router)
feed_router.include_router(feed_user.router)
feed_router.include_router(feed_post_like.router)
feed_router.include_router(feed_post_comment.router)
feed_router.include_router(feed_popup.router)
