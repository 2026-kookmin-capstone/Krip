"""채팅 도메인 Redis 키 / TTL 상수.

키 문자열을 코드 전체에 흩뿌리지 않는 목적 — 네이밍 실수 한 번으로 dedupe/세션이
다른 키 공간을 쓰게 되는 사고를 방지한다. `ARCHITECTURE_LITE.md` §3.3 테이블과
1:1 대응.
"""

# ─────────────────────────────────────────────────────────────
# TTL (seconds)
# ─────────────────────────────────────────────────────────────
SESSION_TTL = 90            # sess:{sid}, ws_route:{sid}, sessions ZSET score 연장 주기와 동일
ROOM_MEMBERS_TTL = 600      # room:members:{R} 캐시 — RDB fallback 전제이므로 짧게 잡아도 됨
ROOM_BLOCKS_TTL = 600       # room:blocks:{R} 캐시 — friend 도메인 hook 미호출 시 stale 상한
RATE_LIMIT_TTL = 1          # rate:msg:{uid} — 1초 윈도우
DEDUPE_TTL = 600            # dedupe:{uid}:{cmid} — 클라 재전송 최대 갭보다 충분히 길게

# ─────────────────────────────────────────────────────────────
# 임계값
# ─────────────────────────────────────────────────────────────
RATE_LIMIT_THRESHOLD = 10   # 초당 메시지 상한 (§5.1-3)
MAX_SESSIONS_PER_USER = 10  # 유저당 동시 세션 상한 (§3.4)

# force_jump 파라미터 — recover_and_incr 의 base gap 과 맞춰 간섭 최소화
SEQ_FORCE_JUMP_GAP = 1000
SEQ_FORCE_JUMP_JITTER_MAX = 10000
SEQ_RECOVER_GAP = 1000      # mongo_max + SEQ_RECOVER_GAP 를 base 로 사용


# ─────────────────────────────────────────────────────────────
# 키 빌더 — DB 0 (hot)
# ─────────────────────────────────────────────────────────────
def sess_key(session_id: str) -> str:
    return f"sess:{session_id}"


def sessions_key(user_id: str) -> str:
    return f"sessions:{user_id}"


def ws_route_key(session_id: str) -> str:
    return f"ws_route:{session_id}"


def unread_key(user_id: str) -> str:
    return f"unread:{user_id}"


def room_seq_key(room_id: str) -> str:
    return f"room:seq:{room_id}"


def room_members_key(room_id: str) -> str:
    return f"room:members:{room_id}"


def room_blocks_key(room_id: str) -> str:
    return f"room:blocks:{room_id}"


def rate_msg_key(user_id: str) -> str:
    return f"rate:msg:{user_id}"


DIRTY_CHAT_ROOM_KEY = "dirty:chat_room"   # reconcile worker 가 소비하는 SET


# ─────────────────────────────────────────────────────────────
# 키 빌더 — DB 1 (dedupe 격리)
# ─────────────────────────────────────────────────────────────
def dedupe_key(user_id: str, client_msg_id: str) -> str:
    return f"dedupe:{user_id}:{client_msg_id}"
