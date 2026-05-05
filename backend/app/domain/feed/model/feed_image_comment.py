"""피드 이미지 댓글 (PostgreSQL).

설계:
    - `comment_id` PK + (image_id, user_id) FK — 한 이미지에 여러 유저가 여러 댓글 가능.
    - 양쪽 FK ON DELETE CASCADE — 유저 탈퇴 또는 이미지 삭제 시 댓글 자동 정리.
    - `ix_feed_image_comment_image_created (image_id, created_at)` — 이미지별 댓글
      시간순 페이지네이션을 단일 인덱스로 커버.
    - `ck_feed_image_comment_min_length` — 빈 문자열 댓글 차단 (DB-level 방어선).
"""
from sqlalchemy import Column, String, DateTime, ForeignKey, Index, CheckConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from app.util.id_generator import generate_feed_image_comment_id
from app.database.session import Base


# 댓글 본문 한도
COMMENT_MAX_LENGTH = 500


class FeedImageComment(Base):
    """피드 이미지 댓글."""
    __tablename__ = "feed_image_comment"

    comment_id = Column(String(50), primary_key=True, default=generate_feed_image_comment_id)  # 댓글 고유 ID
    image_id = Column(String(50), ForeignKey("feed_image.image_id", ondelete="CASCADE"), nullable=False)  # 대상 이미지 ID
    user_id = Column(String(50), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)  # 작성자 ID
    content = Column(String(COMMENT_MAX_LENGTH), nullable=False)  # 댓글 본문 (1~500자)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())  # 작성 시각
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())  # 마지막 수정 시각

    user = relationship("User", backref="feed_image_comments")
    image = relationship("FeedImage", back_populates="comments")

    __table_args__ = (
        Index("ix_feed_image_comment_image_created", "image_id", "created_at"),  # 이미지별 시간순 페이지네이션
        CheckConstraint("char_length(content) >= 1", name="ck_feed_image_comment_min_length"),  # 빈 댓글 방지
    )

    def __repr__(self):
        return f"<FeedImageComment(comment_id={self.comment_id}, image_id={self.image_id}, user_id={self.user_id})>"
