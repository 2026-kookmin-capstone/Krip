"""피드 게시물 좋아요 라우터 Pydantic 스키마.

응답이 단순해 별도 DTO 없이 service → router 로 primitive 가 흐른다 (tripmate 패턴).
"""
from typing import List
from pydantic import BaseModel, Field


class LikeResponse(BaseModel):
    """좋아요 추가/취소 응답 — 클라이언트가 즉시 카운트 업데이트할 수 있도록."""
    post_id: str = Field(..., description="피드 게시물 고유 ID")
    like_count: int = Field(..., description="현재 좋아요 수")


class LikedUsersResponse(BaseModel):
    """좋아요 누른 유저 ID 목록 — 최신순. (프로필 정보는 추후 batch 조회로 별도 endpoint 분리)"""
    post_id: str = Field(..., description="피드 게시물 고유 ID")
    user_ids: List[str] = Field(..., description="좋아요 누른 유저 ID 목록 (최신순)")
