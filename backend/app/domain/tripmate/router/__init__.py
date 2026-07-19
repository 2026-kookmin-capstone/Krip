from fastapi import APIRouter

from app.domain.tripmate.router import tripmate_image, tripmate_post, tripmate_search_history


tripmate_router = APIRouter(prefix="/tripmate")
tripmate_router.include_router(tripmate_post.router)
tripmate_router.include_router(tripmate_search_history.router)
tripmate_router.include_router(tripmate_image.router)
