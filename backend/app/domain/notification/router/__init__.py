from fastapi import APIRouter

from app.domain.notification.router import fcm_token


notification_router = APIRouter(prefix="/notification")
notification_router.include_router(fcm_token.router)
