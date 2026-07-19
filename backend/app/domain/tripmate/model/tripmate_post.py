import enum

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    literal_column,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database.session import Base
from app.util.id_generator import generate_tripmate_post_id


class PreferredGender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"
    ANY = "any"


class CompanionType(str, enum.Enum):
    FRIEND = "friend"
    FAMILY = "family"
    COUPLE = "couple"
    SOLE = "sole"


class TripmatePost(Base):
    """여행 메이트 모집 게시글"""
    __tablename__ = "tripmate_post"
    # `eager_defaults=True` — server-eval `updated_at` 을 RETURNING 으로 즉시 ORM 반영.
    # async 환경에서 lazy-load (MissingGreenlet) 회피 표준 패턴.
    __mapper_args__ = {"eager_defaults": True}

    post_id = Column(String(50), primary_key=True, default=generate_tripmate_post_id)
    user_id = Column(String(50), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    title = Column(String(100), nullable=False)
    content = Column(String(500), nullable=False)
    preferred_age_min = Column(Integer, nullable=False)
    preferred_age_max = Column(Integer, nullable=False)
    preferred_gender = Column(Enum(PreferredGender), nullable=False)
    region = Column(String(100), nullable=False)
    travel_start_date = Column(Date, nullable=False)
    travel_end_date = Column(Date, nullable=False)
    companion_type = Column(Enum(CompanionType), nullable=False)
    is_displayed = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    user = relationship("User", backref="tripmate_posts")
    images = relationship("TripmatePostImage", back_populates="post", cascade="all, delete-orphan")
    likes = relationship("TripmatePostLike", back_populates="post", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_tripmate_post_user_id", "user_id"),
        Index("ix_tripmate_post_region", "region"),
        Index("ix_tripmate_post_travel_dates", "travel_start_date", "travel_end_date"),
        # 브라우즈 피드 keyset (created_at DESC, post_id DESC) 용 — ASC 인덱스의
        # backward scan 으로 커버. 숨김 글 제외 부분 인덱스로 크기 최소화.
        Index(
            "ix_tripmate_post_displayed_created",
            "created_at",
            "post_id",
            postgresql_where=literal_column("is_displayed = true"),
        ),
        CheckConstraint("preferred_age_min <= preferred_age_max", name="ck_preferred_age_range"),
        CheckConstraint("travel_start_date <= travel_end_date", name="ck_travel_date_range"),
        CheckConstraint("char_length(content) >= 10", name="ck_content_min_length"),
    )

    def __repr__(self):
        return f"<TripmatePost(post_id={self.post_id}, user_id={self.user_id}, title={self.title})>"
