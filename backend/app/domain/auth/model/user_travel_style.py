from sqlalchemy import Column, String, Enum, ForeignKey, Index
from sqlalchemy.orm import relationship
import enum

from app.util.id_generator import generate_travel_style_id
from app.database.session import Base


class TravelStyle(str, enum.Enum):
    ACTIVITY = "activity"
    RELAXATION = "relaxation"
    TOURISM = "tourism"
    SHOPPING = "shopping"
    FOOD = "food"


class UserTravelStyle(Base):
    __tablename__ = "user_travel_style"

    id = Column(String(50), primary_key=True, default=generate_travel_style_id)
    user_id = Column(String(50), ForeignKey("users.user_id", ondelete="CASCADE"), nullable=False)
    style = Column(Enum(TravelStyle), nullable=False)

    user = relationship("User", back_populates="travel_styles")

    __table_args__ = (
        Index("ix_user_travel_style_user_id", "user_id"),
    )

    def __repr__(self):
        return f"<UserTravelStyle(id={self.id}, user_id={self.user_id}, style={self.style})>"
