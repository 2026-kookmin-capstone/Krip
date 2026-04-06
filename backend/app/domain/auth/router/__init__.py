from fastapi import APIRouter

from app.domain.auth.router.profile import me
from app.domain.auth.router.login import login, register, logout


auth_router = APIRouter(prefix="/auth")
auth_router.include_router(login.router)
auth_router.include_router(register.router)
auth_router.include_router(logout.router)
auth_router.include_router(me.router)