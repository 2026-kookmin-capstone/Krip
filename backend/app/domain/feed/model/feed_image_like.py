"""피드 이미지 좋아요 (PostgreSQL).

tripmate_post_like 패턴 그대로:
    - composite PK `(user_id, image_id)` 로 유저당 이미지 1회 제한 (DB-level 제약).
    - 양쪽 FK ON DELETE CASCADE — 유저 탈퇴 또는 이미지 삭제 시 자동 정리.
    - `ix_feed_image_like_image_id` 로 이미지별 좋아요 수 / 누른 유저 목록 조회 최적화.
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Index
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import relationship

from app.database.session import Base


class FeedImageLike(Base):
    """피드 이미지 좋아요 (유저당 이미지 1회 제한)."""
    __tablename__ = "feed_image_like"

    user_id = Column(String(50), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)  # 좋아요 누른 유저 ID
    image_id = Column(String(50), ForeignKey("feed_image.image_id", ondelete="CASCADE"), primary_key=True)  # 대상 이미지 ID
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())  # 좋아요 누른 시각

    user = relationship("User", backref="feed_image_likes")
    image = relationship("FeedImage", back_populates="likes")

    __table_args__ = (
        Index("ix_feed_image_like_image_id", "image_id"),  # 이미지별 like_count / 좋아요 누른 유저 목록 조회용
    )

    def __repr__(self):
        return f"<FeedImageLike(user_id={self.user_id}, image_id={self.image_id})>"
