from fastapi import APIRouter

from app.domain.auth.router import app_login, login, logout, profile, register, withdraw


auth_router = APIRouter(prefix="/auth")
auth_router.include_router(login.router)
auth_router.include_router(app_login.router)
auth_router.include_router(register.router)
auth_router.include_router(logout.router)
auth_router.include_router(profile.router)
auth_router.include_router(withdraw.router)