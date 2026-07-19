from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class RegisterFcmTokenBody(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "token": "covcGz6bkRNvEOSa9PNBFy:APA91bF...",
            }
        }
    )

    token: str = Field(..., min_length=1, max_length=512, description="등록할 FCM 디바이스 토큰")


class UnregisterFcmTokenBody(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "token": "covcGz6bkRNvEOSa9PNBFy:APA91bF...",
            }
        }
    )

    token: str = Field(..., min_length=1, max_length=512, description="해제할 FCM 디바이스 토큰")


class FcmTokenResponse(BaseModel):
    fcm_token_id: str = Field(..., description="등록된 토큰 row 의 서버 ID")
    created_at: datetime = Field(..., description="등록 시각")
