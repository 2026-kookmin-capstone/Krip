from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint, Index

from app.util.id_generator import generate_fcm_token_id
from app.database.session import Base


class FcmToken(Base):
    """FCM 디바이스 토큰 — 한 유저가 여러 디바이스에서 푸시를 받을 수 있도록 1:N 매핑.

    - `token` UNIQUE — FCM 토큰 자체가 디바이스 식별자. 동일 토큰이 다른 user_id 로
      재등록되면 서비스 계층에서 ON CONFLICT (token) DO UPDATE 로 소유자만 교체.
    - 사용자 탈퇴 시 `users` row 삭제 → ondelete CASCADE 로 자동 정리.
    - 발송 응답이 UNREGISTERED / INVALID_ARGUMENT 면 해당 row 를 즉시 DELETE 하여
      만료 토큰 누적을 막는다 (정리는 서비스 계층 책임).
    """

    __tablename__ = "fcm_token"

    fcm_token_id = Column(String(50), primary_key=True, default=generate_fcm_token_id)
    user_id = Column(String(50), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    token = Column(String(512), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())

    user = relationship("User", backref="fcm_tokens")

    __table_args__ = (
        UniqueConstraint("token", name="uq_fcm_token_token"),
        Index("ix_fcm_token_user_id", "user_id"),
    )

    def __repr__(self):
        return f"<FcmToken(fcm_token_id={self.fcm_token_id}, user_id={self.user_id}, token={self.token[:16]}...)>"
