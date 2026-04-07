from fastapi import APIRouter

from app.domain.auth.router import auth_router


api_router = APIRouter(prefix="/api")

api_router.include_router(auth_router)