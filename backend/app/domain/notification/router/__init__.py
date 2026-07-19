from fastapi import APIRouter

from app.domain.notification.router import fcm_token, inbox, mute


notification_router = APIRouter(prefix="/notification")
notification_router.include_router(fcm_token.router)
notification_router.include_router(mute.router)
notification_router.include_router(inbox.router)
