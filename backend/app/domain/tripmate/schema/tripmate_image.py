from typing import List
from pydantic import BaseModel, Field


# ──────────────────── Response ────────────────────

class ImageUploadResponse(BaseModel):
    image_id: str = Field(..., description="이미지 고유 ID")
    image_url: str = Field(..., description="이미지 URL")


class ImageUploadListResponse(BaseModel):
    images: List[ImageUploadResponse] = Field(..., description="업로드된 이미지 목록")


class CleanupResponse(BaseModel):
    deleted_count: int = Field(..., description="삭제된 고아 이미지 수")
