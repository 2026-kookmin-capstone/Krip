"""채팅 Phase 3 E2E smoke 테스트 — reconcile job + unread 복구.

run_smoke.sh 가 Phase 1+2 smoke 를 통과시킨 뒤 이 스크립트를 이어서 돌린다. Phase 1+2 와
같은 스택(postgres/redis/mongo)과 유저(A/B/C) 를 재사용.

시나리오:
    [1/2] reconcile_last_message:
        - A↔B direct 방에 새 메시지 1건 송신
        - chat_room.last_message_* 를 의도적으로 NULL 로 덮어 씀 (정합성 깨짐 재현)
        - `dirty:chat_room` 에 room_id SADD (워커 큐에 투입)
        - 워커가 수 초 안에 pop → Mongo aggregate → RDB UPDATE 까지 수행
        - RDB last_message_server_seq 가 실제 최신 seq 와 일치하는지 확인

    [2/2] recover_unread_for_user:
        - 새 direct 방 A↔C 를 만들고 A → C 로 메시지 2건 송신 → Redis `unread:{C}` 누적
        - Redis 에서 `unread:{C}` 을 DEL (Redis flush 시나리오 재현)
        - C 가 WS 연결 → 연결 직후 서버가 백그라운드 복구를 trigger
        - C 에게 `unread_synced` 이벤트가 오는지 대기 + counts 가 실제 메시지 수와 일치

실행 전제: `.env.smoke` 의 `CHAT_RECONCILE_INTERVAL_SEC=1` 로 tick 1초.
"""
import asyncio
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
import jwt
import redis.asyncio as aioredis
import websockets


# 포트 override — 로컬에서 8100 이 점유됐을 때 SMOKE_PORT=8110 등으로 피할 수 있게.
_PORT = int(os.getenv("SMOKE_PORT", "8100"))
BASE_URL = f"http://127.0.0.1:{_PORT}"
WS_URL = f"ws://127.0.0.1:{_PORT}/api/ws/chat"
ORIGIN = "http://localhost:3000"

JWT_SECRET = "smoke-jwt-secret-key-for-local-testing"
JWT_ALGO = "HS256"
COOKIE_NAME = "utk"
ACCESS_TOKEN = "smoke-access-token"

USER_A = "USER_SMOKE_A"
USER_B = "USER_SMOKE_B"
USER_C = "USER_SMOKE_C"

DIRTY_CHAT_ROOM_KEY = "dirty:chat_room"

# 워커 tick 이 1초이므로 2~3초 여유. 느린 CI 대비 5초 상한.
RECONCILE_WAIT_SEC = 5.0
UNREAD_RECOVER_WAIT_SEC = 5.0


# ──────────────────── 유틸 ────────────────────

def make_jwt(user_id: str) -> str:
    payload = {
        "user_id": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def log(label: str, msg: str) -> None:
    print(f"  [{label}] {msg}")


def assert_eq(actual, expected, label: str) -> None:
    if actual != expected:
        raise AssertionError(f"{label}: expected={expected!r} actual={actual!r}")


def make_client(user_id: str) -> httpx.AsyncClient:
    token = make_jwt(user_id)
    return httpx.AsyncClient(
        base_url=BASE_URL,
        cookies={COOKIE_NAME: token},
        headers={
            "Origin": ORIGIN,
            "Authorization": f"Bearer {ACCESS_TOKEN}",
        },
        timeout=10.0,
    )


async def connect_ws(user_id: str):
    token = make_jwt(user_id)
    return await websockets.connect(
        WS_URL,
        additional_headers={
            "Origin": ORIGIN,
            "Cookie": f"{COOKIE_NAME}={token}",
        },
    )


async def recv_until(ws, target_type: str, timeout: float = 3.0) -> dict:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise AssertionError(f"{target_type} 이벤트 대기 타임아웃 ({timeout}s)")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        evt = json.loads(raw)
        if evt.get("type") == target_type:
            return evt


async def send_json(ws, payload: dict) -> None:
    await ws.send(json.dumps(payload))


async def redis_client() -> aioredis.Redis:
    """hot DB (0) 클라이언트. smoke_test 가 직접 Redis 검증용."""
    host = os.getenv("REDIS_HOST", "127.0.0.1")
    port = int(os.getenv("REDIS_PORT", "6479"))
    db = int(os.getenv("REDIS_DB", "0"))
    return aioredis.from_url(
        f"redis://{host}:{port}/{db}",
        decode_responses=True,
        encoding="utf-8",
    )


async def pg_connection() -> asyncpg.Connection:
    return await asyncpg.connect(
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=int(os.getenv("POSTGRES_PORT", "5532")),
        user=os.getenv("POSTGRES_USER", "cho"),
        password=os.getenv("POSTGRES_PASSWORD", "hyeonsang"),
        database=os.getenv("POSTGRES_NAME", "chohyeonsang"),
    )


# ──────────────────── [1/2] reconcile_last_message ────────────────────

async def section_reconcile_last_message() -> None:
    """A↔B 방에 메시지 송신 후 RDB 정합성 일부러 깨뜨리고 워커가 복구하는지 확인."""
    # 1) direct 방 확보 (Phase 1+2 smoke 가 이미 만들어뒀지만 멱등 보장)
    async with make_client(USER_A) as client_a:
        log("REST", "POST /chat/rooms/direct (A → B)")
        r = await client_a.post("/api/chat/rooms/direct", json={"peer_user_id": USER_B})
        assert r.status_code == 201, f"방 생성 실패: {r.status_code} {r.text}"
        room_id = r.json()["chat_room_id"]
        log("REST", f"    room_id={room_id}")

    # 2) WS 로 A → B 메시지 1건 발행
    ws_a = await connect_ws(USER_A)
    await recv_until(ws_a, "connected")
    cmid = f"cmid-reconcile-{int(time.time() * 1000)}"
    await send_json(ws_a, {
        "op": "send",
        "room_id": room_id,
        "client_msg_id": cmid,
        "type": "text",
        "content": "reconcile 타겟 메시지",
    })
    ack = await recv_until(ws_a, "message.sent")
    message_id = ack["message_id"]
    real_seq = ack["server_seq"]
    await ws_a.close()
    log("WS", f"    메시지 전송 OK: seq={real_seq}")

    # 3) RDB chat_room.last_message_* 를 의도적으로 NULL 로 내림 — 정합성 깨뜨림
    conn = await pg_connection()
    try:
        await conn.execute(
            """
            UPDATE chat_room
            SET last_message_id = NULL,
                last_message_server_seq = NULL,
                last_message_at = NULL
            WHERE chat_room_id = $1
            """,
            room_id,
        )
        row = await conn.fetchrow(
            "SELECT last_message_server_seq FROM chat_room WHERE chat_room_id = $1",
            room_id,
        )
        assert row["last_message_server_seq"] is None, "NULL 세팅 실패"
        log("PG", "    chat_room.last_message_* = NULL (정합성 깨짐)")
    finally:
        await conn.close()

    # 4) Redis dirty:chat_room 에 room_id 투입 (워커 큐에 엔트리)
    rc = await redis_client()
    try:
        await rc.sadd(DIRTY_CHAT_ROOM_KEY, room_id)
        size_before = await rc.scard(DIRTY_CHAT_ROOM_KEY)
        assert size_before >= 1, "SADD 실패"
        log("REDIS", f"    SADD dirty:chat_room — scard={size_before}")

        # 5) 워커 tick(1초) 대기 + polling
        log("WORKER", f"    reconcile 대기 (최대 {RECONCILE_WAIT_SEC}s)…")
        drained = False
        deadline = time.time() + RECONCILE_WAIT_SEC
        while time.time() < deadline:
            is_member = await rc.sismember(DIRTY_CHAT_ROOM_KEY, room_id)
            if not is_member:
                drained = True
                break
            await asyncio.sleep(0.2)
        if not drained:
            raise AssertionError(
                f"dirty:chat_room 에서 {RECONCILE_WAIT_SEC}s 내에 {room_id} 가 pop 되지 않음"
            )
        log("WORKER", "    dirty 에서 pop 확인")
    finally:
        await rc.aclose()

    # 6) RDB last_message_server_seq 가 복구됐는지 확인 — Mongo 진실값과 일치해야 함
    conn = await pg_connection()
    try:
        row = await conn.fetchrow(
            """
            SELECT last_message_id, last_message_server_seq, last_message_at
            FROM chat_room WHERE chat_room_id = $1
            """,
            room_id,
        )
        assert row is not None, "방 레코드 사라짐"
        assert_eq(row["last_message_server_seq"], real_seq, "복구된 server_seq")
        assert_eq(row["last_message_id"], message_id, "복구된 message_id")
        assert row["last_message_at"] is not None, "복구된 last_message_at"
        log("PG", f"    복구 확인: server_seq={real_seq}, message_id={message_id}")
    finally:
        await conn.close()


# ──────────────────── [2/2] recover_unread_for_user ────────────────────

async def section_recover_unread() -> None:
    """A↔C 방에 메시지 누적 후 Redis unread:{C} DEL → C 재연결 시 복구 trigger."""
    # 1) A↔C direct 방 확보
    async with make_client(USER_A) as client_a:
        r = await client_a.post("/api/chat/rooms/direct", json={"peer_user_id": USER_C})
        assert r.status_code == 201, f"A↔C 방 생성 실패: {r.status_code} {r.text}"
        room_id = r.json()["chat_room_id"]
        log("REST", f"    A↔C room_id={room_id}")

    # 2) A → C 로 2건 송신 (C 의 unread 누적)
    ws_a = await connect_ws(USER_A)
    await recv_until(ws_a, "connected")
    for i in range(2):
        cmid = f"cmid-unread-{int(time.time() * 1000)}-{i}"
        await send_json(ws_a, {
            "op": "send",
            "room_id": room_id,
            "client_msg_id": cmid,
            "type": "text",
            "content": f"unread 대상 메시지 {i + 1}",
        })
        await recv_until(ws_a, "message.sent")
    await ws_a.close()
    log("WS", "    A → C 메시지 2건 발행")

    # 서버 내부 파이프라인이 unread HINCRBY 끝낼 수 있도록 아주 짧게 양보
    await asyncio.sleep(0.3)

    # 3) Redis `unread:{USER_C}` 를 DEL — flush 시나리오 재현
    rc = await redis_client()
    try:
        unread_key = f"unread:{USER_C}"
        before = await rc.hgetall(unread_key)
        assert int(before.get(room_id, 0)) >= 2, (
            f"A→C 메시지 2건 보낸 후 unread:{USER_C}:{room_id} 가 2 이상이어야 함, 실제={before}"
        )
        log("REDIS", f"    pre-DEL: {unread_key} = {before}")
        await rc.delete(unread_key)
        exists = await rc.exists(unread_key)
        assert exists == 0, f"DEL 후에도 키 존재: exists={exists}"
        log("REDIS", f"    DEL {unread_key} 완료")
    finally:
        await rc.aclose()

    # 4) C 가 WS 재연결 → 백그라운드 `recover_unread_for_user` trigger → `unread_synced` push
    ws_c = await connect_ws(USER_C)
    try:
        await recv_until(ws_c, "connected")
        log("WS", f"    C connected — recover 대기 (최대 {UNREAD_RECOVER_WAIT_SEC}s)")

        evt = await recv_until(
            ws_c, "unread_synced", timeout=UNREAD_RECOVER_WAIT_SEC,
        )
        counts = evt.get("counts", {})
        got = int(counts.get(room_id, -1))
        # A→C 송신 2건. 단, 앞선 section_reconcile_last_message 에서 C 는 관여 안 했고,
        # Phase 1+2 smoke 와 겹칠 가능성이 있어 정확한 2 대신 "≥2" 로 검증 (A↔C 방 한정).
        assert got >= 2, f"복구된 count 가 2 이상이어야 함. room={room_id}, got={got}, all={counts}"
        log("WS", f"    unread_synced 수신: {room_id}={got}")
    finally:
        await ws_c.close()

    # 5) Redis 에 실제 HSET 반영 확인 (백그라운드 경로 완결성)
    rc = await redis_client()
    try:
        after = await rc.hgetall(f"unread:{USER_C}")
        assert int(after.get(room_id, 0)) >= 2, f"HSET 반영 안 됨: {after}"
        log("REDIS", f"    post-recover: unread:{USER_C}={after}")
    finally:
        await rc.aclose()


# ──────────────────── 메인 ────────────────────

async def main() -> int:
    print("=" * 70)
    print("Phase 3 Chat Smoke Test (reconcile + unread recovery)")
    print("=" * 70)

    print("\n[1/2] WORKER: reconcile_last_message (dirty → Mongo → RDB 복구)")
    await section_reconcile_last_message()

    print("\n[2/2] WORKER: recover_unread_for_user (WS 재연결 시 배경 복구)")
    await section_recover_unread()

    print("\n" + "=" * 70)
    print("ALL PHASE 3 SMOKE PASSED ✓")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        code = asyncio.run(main())
    except AssertionError as e:
        print(f"\nFAIL: {e}", file=sys.stderr)
        code = 1
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"\nERROR: {type(e).__name__}: {e}", file=sys.stderr)
        code = 2
    sys.exit(code)
