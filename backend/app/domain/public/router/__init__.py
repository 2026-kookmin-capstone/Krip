from fastapi import APIRouter

from app.domain.public.router import share


public_router = APIRouter(prefix="/public")
public_router.include_router(share.router)
