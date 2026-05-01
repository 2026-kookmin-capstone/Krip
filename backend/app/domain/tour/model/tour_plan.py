from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, Index, CheckConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.util.id_generator import generate_tour_plan_id
from app.database.session import Base


class TourPlan(Base):
    """저장된 여행 플랜 (RDB)

    - AI가 생성한 일정을 사용자가 저장 후 직접 편집 가능
    - 카드(여행지) 목록은 TourPlanItem 으로 분리되어 day/position 으로 정렬됨
    """

    __tablename__ = "tour_plan"

    plan_id = Column(String(50), primary_key=True, default=generate_tour_plan_id)  # 플랜 고유 ID
    user_id = Column(String(50), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)  # 작성자 ID
    title = Column(String(100), nullable=True)  # 사용자 지정 플랜 이름 (선택)
    travel_days = Column(Integer, nullable=False)  # 여행 일수 (1 이상)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())  # 저장 시각
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())  # 마지막 편집 시각

    items = relationship(
        "TourPlanItem",
        back_populates="plan",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_tour_plan_user_id", "user_id"),
        CheckConstraint("travel_days >= 1", name="ck_tour_plan_travel_days_min"),
    )

    def __repr__(self):
        return f"<TourPlan(plan_id={self.plan_id}, user_id={self.user_id}, days={self.travel_days})>"
