from pydantic import BaseModel, Field


class MessageResponse(BaseModel):
    message: str = Field(..., description="응답 메시지")
