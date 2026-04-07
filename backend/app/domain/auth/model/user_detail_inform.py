from sqlalchemy import Column, String, Integer, Enum, ForeignKey
from sqlalchemy.orm import relationship
import enum

from app.database.session import Base


class Gender(str, enum.Enum):
    MALE = "male"
    FEMALE = "female"


class UserDetailInform(Base):
    __tablename__ = "user_detail_inform"

    user_id = Column(String(50), ForeignKey("users.user_id", ondelete="CASCADE"), primary_key=True)
    email = Column(String(255), nullable=False, index=True)
    user_name = Column(String(100), nullable=False)
    phone_number = Column(String(20), nullable=True)
    age = Column(Integer, nullable=True)
    gender = Column(Enum(Gender), nullable=True)

    user = relationship("User", back_populates="detail")


    def __repr__(self):
        return f"<UserDetailInform(user_id={self.user_id}, email={self.email}, name={self.user_name})>"