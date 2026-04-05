from fastapi import APIRouter

from app.domain.auth.router.test import cookie
from app.domain.auth.router.login import login


auth_router = APIRouter(prefix="/auth")
auth_router.include_router(cookie.router)
auth_router.include_router(login.router)