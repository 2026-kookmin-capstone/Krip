"""채팅 Phase 1 E2E smoke 테스트.

run_smoke.sh 가 FastAPI 서버를 띄운 뒤 이 스크립트를 실행한다.

시나리오:
    1. 두 테스트 유저(A, B) 에 대해 JWT 수동 서명
    2. [REST] A 가 POST /api/chat/rooms/direct 로 B 와의 1:1 방 생성
    3. [REST] A 가 GET /api/chat/rooms — 방 리스트에 1건 포함 확인
    4. [REST] 같은 요청 2번 → 같은 chat_room_id (idempotent)
    5. [WS]  B 가 WS 먼저 연결 → connected 이벤트 수신
    6. [WS]  A 가 WS 연결 → connected 이벤트 수신
    7. [WS]  A 가 send op → A 에게는 message.sent, B 에게는 message.new 수신
    8. [REST] A 가 GET /chat/rooms/{id}/messages?before_server_seq=999999 — 1건 + has_more=False
    9. [WS]  동일 client_msg_id 재전송 → ValueError (server_error) 수신

실패 즉시 raise + sys.exit(1).
"""
import asyncio
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import websockets


BASE_URL = "http://127.0.0.1:8100"
WS_URL = "ws://127.0.0.1:8100/api/ws/chat"
ORIGIN = "http://localhost:3000"

JWT_SECRET = "smoke-jwt-secret-key-for-local-testing"
JWT_ALGO = "HS256"
COOKIE_NAME = "utk"
ACCESS_TOKEN = "smoke-access-token"  # BearerTokenMiddleware 통과용 (.env.smoke 와 동기)

USER_A = "USER_SMOKE_A"
USER_B = "USER_SMOKE_B"


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


# ──────────────────── WS 헬퍼 ────────────────────

async def connect_ws(user_id: str, token: str) -> websockets.WebSocketClientProtocol:
    ws = await websockets.connect(
        WS_URL,
        additional_headers={
            "Origin": ORIGIN,
            "Cookie": f"{COOKIE_NAME}={token}",
        },
    )
    return ws


async def recv_json(ws, timeout: float = 3.0) -> dict:
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)


async def send_json(ws, payload: dict) -> None:
    await ws.send(json.dumps(payload))


# ──────────────────── 개별 테스트 ────────────────────

async def test_create_direct_room_and_list(client_a: httpx.AsyncClient) -> str:
    log("REST", "POST /chat/rooms/direct (A → B)")
    r = await client_a.post(
        "/api/chat/rooms/direct",
        json={"peer_user_id": USER_B},
    )
    assert_eq(r.status_code, 201, "create_direct 상태코드")
    body = r.json()
    assert body["type"] == "direct", f"type={body['type']}"
    room_id = body["chat_room_id"]
    assert room_id.startswith("CR_"), f"chat_room_id={room_id}"
    assert body["peer"]["user_id"] == USER_B, "peer.user_id"
    log("REST", f"    → chat_room_id={room_id}")

    log("REST", "GET /chat/rooms")
    r = await client_a.get("/api/chat/rooms")
    assert_eq(r.status_code, 200, "list_rooms 상태코드")
    items = r.json()["items"]
    assert len(items) == 1, f"방 1건 기대, 실제 {len(items)}"
    assert items[0]["chat_room_id"] == room_id

    log("REST", "POST /chat/rooms/direct 두 번째 호출 (idempotent)")
    r2 = await client_a.post(
        "/api/chat/rooms/direct",
        json={"peer_user_id": USER_B},
    )
    assert_eq(r2.status_code, 201, "두번째 호출 상태코드")
    assert r2.json()["chat_room_id"] == room_id, "idempotent 실패"

    return room_id


async def test_ws_send_receive(room_id: str) -> int:
    token_a = make_jwt(USER_A)
    token_b = make_jwt(USER_B)

    log("WS", "B 연결")
    ws_b = await connect_ws(USER_B, token_b)
    connected_b = await recv_json(ws_b)
    assert_eq(connected_b["type"], "connected", "B connected 타입")

    log("WS", "A 연결")
    ws_a = await connect_ws(USER_A, token_a)
    connected_a = await recv_json(ws_a)
    assert_eq(connected_a["type"], "connected", "A connected 타입")

    # A 가 B 에게 메시지 송신
    cmid = f"cmid-smoke-{int(time.time() * 1000)}"
    log("WS", f"A → send op (client_msg_id={cmid})")
    await send_json(ws_a, {
        "op": "send",
        "room_id": room_id,
        "client_msg_id": cmid,
        "type": "text",
        "content": "smoke 테스트 안녕",
    })

    # A 에게 message.sent ACK
    ack = await recv_json(ws_a)
    assert_eq(ack["type"], "message.sent", "A ACK 타입")
    assert_eq(ack["client_msg_id"], cmid, "ACK client_msg_id")
    assert isinstance(ack["server_seq"], int) and ack["server_seq"] >= 1, f"server_seq={ack['server_seq']}"
    log("WS", f"    A ACK: message_id={ack['message_id']}, server_seq={ack['server_seq']}")

    # B 에게 message.new
    evt = await recv_json(ws_b)
    assert_eq(evt["type"], "message.new", "B message.new 타입")
    assert_eq(evt["message"]["server_seq"], ack["server_seq"], "server_seq 일치")
    assert_eq(evt["message"]["content"], "smoke 테스트 안녕", "content 일치")
    assert_eq(evt["message"]["sender_id"], USER_A, "sender_id 일치")
    log("WS", f"    B message.new: content={evt['message']['content']!r}")

    # dedupe 검증 — 같은 client_msg_id 재전송
    log("WS", "A → send op 같은 cmid 재전송 (dedupe 기대)")
    await send_json(ws_a, {
        "op": "send",
        "room_id": room_id,
        "client_msg_id": cmid,
        "type": "text",
        "content": "이건 차단돼야 함",
    })
    dup_ack = await recv_json(ws_a)
    assert_eq(dup_ack["type"], "server_error", "dedupe server_error")
    assert "이미 처리" in dup_ack.get("reason", ""), f"reason={dup_ack.get('reason')}"
    log("WS", f"    dedupe 차단 확인: {dup_ack['reason']}")

    await ws_a.close()
    await ws_b.close()
    return ack["server_seq"]


async def test_messages_history(client_a: httpx.AsyncClient, room_id: str, last_seq: int) -> None:
    log("REST", f"GET /chat/rooms/{room_id}/messages?before_server_seq=999999&limit=10")
    r = await client_a.get(
        f"/api/chat/rooms/{room_id}/messages",
        params={"before_server_seq": 999999, "limit": 10},
    )
    assert_eq(r.status_code, 200, "히스토리 상태코드")
    body = r.json()
    assert_eq(len(body["messages"]), 1, "메시지 1건")
    assert_eq(body["has_more"], False, "has_more=False")
    assert_eq(body["messages"][0]["server_seq"], last_seq, "server_seq 일치")
    log("REST", f"    히스토리 OK — server_seq={last_seq}")


# ──────────────────── 메인 ────────────────────

async def main() -> int:
    print("=" * 70)
    print("Phase 1 Chat Smoke Test")
    print("=" * 70)

    token_a = make_jwt(USER_A)
    cookies_a = {COOKIE_NAME: token_a}

    async with httpx.AsyncClient(
        base_url=BASE_URL,
        cookies=cookies_a,
        headers={
            "Origin": ORIGIN,
            "Authorization": f"Bearer {ACCESS_TOKEN}",
        },
        timeout=10.0,
    ) as client_a:
        print("\n[1/3] REST: 방 생성 + 리스트 + idempotent")
        room_id = await test_create_direct_room_and_list(client_a)

        print("\n[2/3] WS: 양쪽 연결 → 송수신 → dedupe")
        last_seq = await test_ws_send_receive(room_id)

        print("\n[3/3] REST: 메시지 히스토리 페이징")
        await test_messages_history(client_a, room_id, last_seq)

    print("\n" + "=" * 70)
    print("ALL SMOKE PASSED ✓")
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
