"""도메인 고유 ID 생성 — `{PREFIX}_{epoch초}_{uuid4 hex}`."""
import time
import uuid


def _generate(prefix: str, entropy_hex_len: int = 8) -> str:
    return f"{prefix}_{int(time.time())}_{uuid.uuid4().hex[:entropy_hex_len]}"


def generate_user_id() -> str:
    """유저 고유 ID 생성"""
    return _generate("USER")


def generate_travel_style_id() -> str:
    """여행 스타일 고유 ID 생성"""
    return _generate("TS")


def generate_tripmate_post_id() -> str:
    """여행 메이트 게시글 고유 ID 생성"""
    return _generate("TMP")


def generate_tripmate_image_id() -> str:
    """여행 메이트 게시글 이미지 고유 ID 생성"""
    return _generate("TMI")


def generate_favorite_place_id() -> str:
    """즐겨찾기 장소 고유 ID 생성"""
    return _generate("FP")


def generate_friendship_id() -> str:
    """친구 관계 고유 ID 생성"""
    return _generate("FS")


def generate_user_block_id() -> str:
    """유저 차단 고유 ID 생성"""
    return _generate("BLK")


def generate_chat_room_id() -> str:
    """채팅방 고유 ID 생성"""
    return _generate("CR")


def generate_message_id() -> str:
    """채팅 메시지 고유 ID 생성 — MongoDB _id 로 사용. timestamp prefix 로 문자열 정렬 = 시간 정렬"""
    return _generate("MSG", entropy_hex_len=16)


def generate_session_id() -> str:
    """WS 세션 고유 ID 생성 — Redis 세션/라우트 키의 식별자"""
    return _generate("WS")


def generate_tour_plan_id() -> str:
    """여행 플랜 고유 ID 생성"""
    return _generate("TP")


def generate_tour_plan_item_id() -> str:
    """여행 플랜 카드(아이템) 고유 ID 생성"""
    return _generate("TPI")


def generate_fcm_token_id() -> str:
    """FCM 디바이스 토큰 row 고유 ID 생성"""
    return _generate("FCM")


def generate_feed_post_id() -> str:
    """피드 게시물 고유 ID 생성"""
    return _generate("FDP")


def generate_feed_post_comment_id() -> str:
    """피드 게시물 댓글 고유 ID 생성 — prefix `FDC_` (Feed Comment)."""
    return _generate("FDC")
