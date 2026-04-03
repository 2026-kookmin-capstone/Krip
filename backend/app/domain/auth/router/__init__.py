from fastapi import APIRouter

from app.domain.auth.router.test import cookie


auth_router = APIRouter(prefix="/auth")
auth_router.include_router(cookie.router)