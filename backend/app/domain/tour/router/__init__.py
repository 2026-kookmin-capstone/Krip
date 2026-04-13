from fastapi import APIRouter

from app.domain.tour.router import place


tour_router = APIRouter(prefix="/tour")
tour_router.include_router(place.router)
