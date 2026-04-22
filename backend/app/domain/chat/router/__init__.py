from fastapi import APIRouter

from app.domain.chat.router import chat_rest
from app.domain.chat.router import chat_ws


# REST (/api/chat/rooms/*) 와 WS (/api/ws/chat) 는 경로 뿌리가 달라 두 라우터로 분리.
chat_rest_router = APIRouter(prefix="/chat")
chat_rest_router.include_router(chat_rest.router)

chat_ws_router = APIRouter(prefix="/ws")
chat_ws_router.include_router(chat_ws.router)
