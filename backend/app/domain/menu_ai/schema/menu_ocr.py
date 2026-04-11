from typing import List
from pydantic import BaseModel, Field


# ──────────────────── Response ────────────────────

class MenuResponse(BaseModel):
    original_name: str = Field(..., description="원본 한국어 메뉴명 (오타 포함 그대로)")
    english_name: str = Field(..., description="영어 번역 메뉴명")
    description: str = Field(..., description="영어 메뉴 설명")
    price: int = Field(..., description="가격 (정수, 통화 기호 제거)")


class MenuOcrResponse(BaseModel):
    menus: List[MenuResponse] = Field(..., description="추출된 메뉴 목록")


class MenuOcrBatchResponse(BaseModel):
    results: List[MenuOcrResponse] = Field(..., description="이미지별 OCR 결과 목록")
