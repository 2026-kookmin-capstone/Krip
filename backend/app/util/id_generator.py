import uuid
from datetime import datetime


def generate_user_id() -> str:
    """유저 고유 ID 생성"""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"USER_{timestamp}_{unique_part}"


def generate_travel_style_id() -> str:
    """여행 스타일 고유 ID 생성"""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"TS_{timestamp}_{unique_part}"