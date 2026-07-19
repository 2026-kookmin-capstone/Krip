from datetime import datetime
from typing import List

from pydantic import BaseModel, Field


class TourSearchHistoryResponse(BaseModel):
    search_name: str = Field(..., description="검색어")
    created_at: datetime = Field(..., description="검색 시각")


class TourSearchHistoryListResponse(BaseModel):
    histories: List[TourSearchHistoryResponse] = Field(..., description="검색 기록 목록 (최신순)")
