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


def generate_friendship_id() -> str:
    """친구 관계 고유 ID 생성"""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"FS_{timestamp}_{unique_part}"


def generate_user_block_id() -> str:
    """유저 차단 고유 ID 생성"""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"BLK_{timestamp}_{unique_part}"


def generate_chat_room_id() -> str:
    """채팅방 고유 ID 생성"""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"CR_{timestamp}_{unique_part}"


def generate_message_id() -> str:
    """채팅 메시지 고유 ID 생성 — MongoDB _id 로 사용. timestamp prefix 로 문자열 정렬 = 시간 정렬"""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"MSG_{timestamp}_{unique_part}"


def generate_session_id() -> str:
    """WS 세션 고유 ID 생성 — Redis 세션/라우트 키의 식별자"""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"WS_{timestamp}_{unique_part}"


def generate_tour_plan_id() -> str:
    """여행 플랜 고유 ID 생성"""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"TP_{timestamp}_{unique_part}"


def generate_tour_plan_item_id() -> str:
    """여행 플랜 카드(아이템) 고유 ID 생성"""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"TPI_{timestamp}_{unique_part}"


def generate_fcm_token_id() -> str:
    """FCM 디바이스 토큰 row 고유 ID 생성"""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"FCM_{timestamp}_{unique_part}"


def generate_feed_post_id() -> str:
    """피드 게시물 고유 ID 생성 — timestamp prefix 라 문자열 정렬 = 시간순."""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"FDP_{timestamp}_{unique_part}"


def generate_feed_post_comment_id() -> str:
    """피드 게시물 댓글 고유 ID 생성 — prefix `FDC_` (Feed Comment)."""
    timestamp = int(datetime.now().timestamp())
    unique_part = uuid.uuid4().hex[:8]
    return f"FDC_{timestamp}_{unique_part}"
