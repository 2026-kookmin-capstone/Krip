from typing import List
from dataclasses import dataclass

from app.domain.auth.model.user_travel_style import TravelStyle
from app.domain.auth.model.user_detail_inform import Gender
from app.domain.auth.model.user import UserStatus
from app.config.oauth import OAuthProvider


@dataclass
class ProfileData:
    user_id: str
    auth_provider: OAuthProvider
    status: UserStatus
    email: str
    user_name: str
    phone_number: str
    age: int
    gender: Gender
    nationality: str
    travel_styles: List[TravelStyle]
