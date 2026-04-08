from fastapi import APIRouter

from app.domain.tripmate.router import tripmate_post


tripmate_router = APIRouter(prefix="/tripmate")
tripmate_router.include_router(tripmate_post.router)
