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


def generate_tripmate_post_id() -> str:
    """여행 메이트 게시글 고유 ID 생성"""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"TMP_{timestamp}_{unique_part}"


def generate_tripmate_image_id() -> str:
    """여행 메이트 게시글 이미지 고유 ID 생성"""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"TMI_{timestamp}_{unique_part}"


def generate_favorite_place_id() -> str:
    """즐겨찾기 장소 고유 ID 생성"""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"FP_{timestamp}_{unique_part}"
