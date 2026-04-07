from typing import List
from pydantic import BaseModel, Field

from app.domain.auth.model.user_travel_style import TravelStyle
from app.domain.auth.model.user_detail_inform import Gender


class ProfileResponse(BaseModel):
    user_id: str = Field(
        ...,
        description="유저 고유 ID",
        examples=["USER_1712345678_abc12345"],
    )
    auth_provider: str = Field(
        ...,
        description="OAuth 제공자",
        examples=["google"],
    )
    status: str = Field(
        ...,
        description="유저 상태",
        examples=["active"],
    )
    email: str = Field(
        ...,
        description="이메일 주소",
        examples=["user@example.com"],
    )
    user_name: str = Field(
        ...,
        description="사용자 이름",
        examples=["조현상"],
    )
    phone_number: str = Field(
        ...,
        description="전화번호",
        examples=["010-1234-5678"],
    )
    age: int = Field(
        ...,
        description="나이",
        examples=[26],
    )
    gender: Gender = Field(
        ...,
        description="성별",
        examples=["male"],
    )
    nationality: str = Field(
        ...,
        description="국적",
        examples=["korea"],
    )
    travel_styles: List[TravelStyle] = Field(
        ...,
        description="여행 스타일 목록",
        examples=[["activity", "food"]],
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "USER_1712345678_abc12345",
                "auth_provider": "google",
                "status": "active",
                "email": "user@example.com",
                "user_name": "조현상",
                "phone_number": "010-1234-5678",
                "age": 26,
                "gender": "male",
                "nationality": "korea",
                "travel_styles": ["activity", "food"],
            }
        }
