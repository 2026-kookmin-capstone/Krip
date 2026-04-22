from fastapi import APIRouter

from app.domain.chat.router import message
from app.domain.chat.router import room
from app.domain.chat.router import ws


# REST (/api/chat/rooms/*, /api/chat/messages/*) 와 WS (/api/ws/chat) 는 경로 뿌리가 달라
# 두 라우터로 분리.
chat_rest_router = APIRouter(prefix="/chat")
chat_rest_router.include_router(room.router)
chat_rest_router.include_router(message.router)

chat_ws_router = APIRouter(prefix="/ws")
chat_ws_router.include_router(ws.router)
