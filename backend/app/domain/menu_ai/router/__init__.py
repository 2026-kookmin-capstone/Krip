from fastapi import APIRouter

from app.domain.menu_ai.router import menu_ocr


menu_ai_router = APIRouter(prefix="/menu-ai")
menu_ai_router.include_router(menu_ocr.router)
