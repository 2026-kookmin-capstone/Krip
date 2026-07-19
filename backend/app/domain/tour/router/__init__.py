from fastapi import APIRouter

from app.domain.tour.router import place, recommend, tour_plan, tour_search_history


tour_router = APIRouter(prefix="/tour")
tour_router.include_router(place.router)
tour_router.include_router(recommend.router)
tour_router.include_router(tour_search_history.router)
tour_router.include_router(tour_plan.router)
