from sqlalchemy import Column, String, DateTime, Boolean, Enum, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import enum

from app.util.id_generator import generate_user_id
from app.database.session import Base
from app.config.oauth import OAuthProvider


class UserStatus(str, enum.Enum):
    ACTIVE = "active" # 활동
    INACTIVE = "inactive" # 휴먼
    SUSPENDED = "suspended" # 정지


class User(Base):
    __tablename__ = "users"

    user_id = Column(String(50), primary_key=True, default=generate_user_id)
    auth_provider = Column(Enum(OAuthProvider), nullable=False)
    auth_provider_id = Column(String(255), nullable=False)
    status = Column(Enum(UserStatus), nullable=False, default=UserStatus.ACTIVE)
    # 전역 알림 차단 — True 면 모든 푸시 차단, NULL = 기본(허용). 명시적 차단만 row 에 적힘.
    notification_muted = Column(Boolean, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    detail = relationship("UserDetailInform", back_populates="user", uselist=False)
    travel_styles = relationship("UserTravelStyle", back_populates="user")

    __table_args__ = (
        UniqueConstraint("auth_provider", "auth_provider_id", name="uq_provider_account"),
        Index("ix_provider_lookup", "auth_provider", "auth_provider_id"),
    )

    def __repr__(self):
        return f"<User(user_id={self.user_id}, provider={self.auth_provider}, status={self.status})>"