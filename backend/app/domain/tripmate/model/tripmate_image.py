from pydantic import Field
from datetime import datetime, timezone
from beanie import Document, Indexed


class TripmateImage(Document):
    """여행 메이트 이미지 관리

    - 업로드된 모든 이미지를 유저별로 추적
    """

    user_id: Indexed(str) = Field(..., description="업로드한 유저 ID")  # type: ignore
    image_id: Indexed(str, unique=True) = Field(..., description="이미지 고유 ID")  # type: ignore
    image_url: str = Field(..., description="Object Storage 이미지 URL")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="이미지 업로드 시각",
    )

    class Settings:
        name = "tripmate_image"
