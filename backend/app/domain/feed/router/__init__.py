from fastapi import APIRouter

from app.domain.feed.router import feed_popup, feed_post, feed_post_comment, feed_post_like, feed_user


feed_router = APIRouter(prefix="/feed")
feed_router.include_router(feed_post.router)
feed_router.include_router(feed_user.router)
feed_router.include_router(feed_post_like.router)
feed_router.include_router(feed_post_comment.router)
feed_router.include_router(feed_popup.router)
