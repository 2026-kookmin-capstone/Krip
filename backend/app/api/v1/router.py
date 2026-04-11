from fastapi import APIRouter

from app.domain.auth.router import auth_router
from app.domain.tripmate.router import tripmate_router


api_router = APIRouter(prefix="/api")

api_router.include_router(auth_router)
api_router.include_router(tripmate_router)