from fastapi import APIRouter

from app.domain.auth.router import auth_router
from app.domain.tripmate.router import tripmate_router
from app.domain.menu_ai.router import menu_ai_router
from app.domain.tour.router import tour_router


api_router = APIRouter(prefix="/api")

api_router.include_router(auth_router)
api_router.include_router(tripmate_router)
api_router.include_router(menu_ai_router)
api_router.include_router(tour_router)