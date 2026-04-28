"""채팅 Phase 1 + Phase 2 E2E smoke 테스트.

run_smoke.sh 가 FastAPI 서버를 띄운 뒤 이 스크립트를 실행한다.

유저 3명 (A, B, C) + 친구관계 (A-B, A-C) 가 seed 된 상태 전제.

시나리오:
    [1/6] REST: 1:1 방 생성 + 리스트 + idempotent
    [2/6] WS:   1:1 방 송수신 + dedupe
    [3/6] REST: 1:1 방 히스토리 (before_server_seq)
    [4/6] REST: 그룹 방 생성 + 시스템 메시지 기록 + catch-up (after_server_seq)
    [5/6] WS:   그룹 방 송수신 + 읽음 표시 (op=read)
    [6/6] REST: 메시지 편집(PATCH) + 삭제(DELETE) + 삭제 마스킹

실패 즉시 raise + sys.exit(1).
"""
import asyncio
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import os

import httpx
import jwt
import websockets


# 로컬에서 다른 서비스가 8100 을 쓰고 있는 경우 SMOKE_PORT=8110 같은 override 가능
_PORT = int(os.getenv("SMOKE_PORT", "8100"))
BASE_URL = f"http://127.0.0.1:{_PORT}"
WS_URL = f"ws://127.0.0.1:{_PORT}/api/ws/chat"
ORIGIN = "http://localhost:3000"

JWT_SECRET = "smoke-jwt-secret-key-for-local-testing"
JWT_ALGO = "HS256"
COOKIE_NAME = "utk"
ACCESS_TOKEN = "smoke-access-token"  # BearerTokenMiddleware 통과용 (.env.smoke 와 동기)

USER_A = "USER_SMOKE_A"
USER_B = "USER_SMOKE_B"
USER_C = "USER_SMOKE_C"


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


# ──────────────────── WS 헬퍼 ────────────────────

async def connect_ws(user_id: str) -> websockets.WebSocketClientProtocol:
    token = make_jwt(user_id)
    return await websockets.connect(
        WS_URL,
        additional_headers={
            "Origin": ORIGIN,
            "Cookie": f"{COOKIE_NAME}={token}",
        },
    )


async def recv_until(ws, target_type: str, timeout: float = 3.0) -> dict:
    """`target_type` 이벤트를 받을 때까지 다른 이벤트는 무시하고 계속 recv.

    `unread_synced` 같은 부차 이벤트가 `connected` 뒤에 섞여 올 수 있어, 기대 타입이
    나올 때까지 드레인하는 게 견고하다.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while True:
        remaining = deadline - loop.time()
        if remaining <= 0:
            raise AssertionError(f"{target_type} 이벤트 대기 타임아웃")
        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
        evt = json.loads(raw)
        if evt.get("type") == target_type:
            return evt


async def send_json(ws, payload: dict) -> None:
    await ws.send(json.dumps(payload))


# ──────────────────── [1/6] direct 방 생성 ────────────────────

async def section_direct_room(client_a: httpx.AsyncClient) -> str:
    log("REST", "POST /chat/rooms/direct (A → B)")
    r = await client_a.post("/api/chat/rooms/direct", json={"peer_user_id": USER_B})
    assert_eq(r.status_code, 201, "create_direct 상태코드")
    body = r.json()
    assert_eq(body["type"], "direct", "type")
    room_id = body["chat_room_id"]
    assert room_id.startswith("CR_"), f"chat_room_id={room_id}"
    assert_eq(body["peer"]["user_id"], USER_B, "peer.user_id")
    log("REST", f"    → chat_room_id={room_id}")

    log("REST", "GET /chat/rooms (1건 포함)")
    r = await client_a.get("/api/chat/rooms")
    assert_eq(r.status_code, 200, "list_rooms 상태코드")
    items = r.json()["items"]
    assert any(i["chat_room_id"] == room_id for i in items), "방 리스트에 direct 없음"

    log("REST", "POST /chat/rooms/direct 재호출 (idempotent)")
    r2 = await client_a.post("/api/chat/rooms/direct", json={"peer_user_id": USER_B})
    assert_eq(r2.status_code, 201, "두번째 호출 상태코드")
    assert_eq(r2.json()["chat_room_id"], room_id, "idempotent")
    return room_id


# ──────────────────── [2/6] direct WS 송수신 + dedupe ────────────────────

async def section_direct_ws_send(direct_room_id: str) -> int:
    log("WS", "B 연결")
    ws_b = await connect_ws(USER_B)
    await recv_until(ws_b, "connected")

    log("WS", "A 연결")
    ws_a = await connect_ws(USER_A)
    await recv_until(ws_a, "connected")

    cmid = f"cmid-{int(time.time() * 1000)}"
    log("WS", f"A → send op (cmid={cmid})")
    await send_json(ws_a, {
        "op": "send",
        "room_id": direct_room_id,
        "client_msg_id": cmid,
        "type": "text",
        "content": "smoke 테스트 안녕",
    })

    ack = await recv_until(ws_a, "message.sent")
    assert_eq(ack["client_msg_id"], cmid, "ACK client_msg_id")
    server_seq = ack["server_seq"]
    log("WS", f"    A ACK: message_id={ack['message_id']}, server_seq={server_seq}")

    evt = await recv_until(ws_b, "message.new")
    assert_eq(evt["message"]["server_seq"], server_seq, "server_seq 일치")
    assert_eq(evt["message"]["content"], "smoke 테스트 안녕", "content 일치")
    assert_eq(evt["message"]["sender_id"], USER_A, "sender_id")
    log("WS", f"    B message.new 수신")

    # dedupe
    log("WS", "A → 같은 cmid 재전송 (dedupe)")
    await send_json(ws_a, {
        "op": "send",
        "room_id": direct_room_id,
        "client_msg_id": cmid,
        "type": "text",
        "content": "차단돼야 함",
    })
    dup = await recv_until(ws_a, "server_error")
    assert "이미 처리" in dup.get("reason", ""), f"reason={dup.get('reason')}"
    log("WS", f"    dedupe 차단: {dup['reason']}")

    await ws_a.close()
    await ws_b.close()
    return server_seq


# ──────────────────── [3/6] direct 히스토리 ────────────────────

async def section_direct_history(
    client_a: httpx.AsyncClient, direct_room_id: str, last_seq: int,
) -> None:
    log("REST", f"GET /rooms/{direct_room_id}/messages?before_server_seq=999999")
    r = await client_a.get(
        f"/api/chat/rooms/{direct_room_id}/messages",
        params={"before_server_seq": 999999, "limit": 10},
    )
    assert_eq(r.status_code, 200, "히스토리 상태코드")
    body = r.json()
    assert_eq(len(body["messages"]), 1, "메시지 1건")
    assert_eq(body["has_more"], False, "has_more=False")
    assert_eq(body["messages"][0]["server_seq"], last_seq, "server_seq 일치")
    log("REST", f"    히스토리 OK — server_seq={last_seq}")


# ──────────────────── [4/6] 그룹 생성 + 시스템 메시지 + catch-up ────────────────────

async def section_group_create_and_catchup(client_a: httpx.AsyncClient) -> str:
    log("REST", "POST /chat/rooms/group (A creator, members=[B, C])")
    r = await client_a.post(
        "/api/chat/rooms/group",
        json={"title": "smoke 그룹", "member_ids": [USER_B, USER_C]},
    )
    assert_eq(r.status_code, 201, "create_group 상태코드")
    body = r.json()
    assert_eq(body["type"], "group", "type")
    assert_eq(body["title"], "smoke 그룹", "title")
    assert body["peer"] is None, "group 방은 peer=None"
    room_id = body["chat_room_id"]
    log("REST", f"    → group room_id={room_id}")

    # catch-up — after_server_seq=0 으로 전체 히스토리 (system "created" 1건)
    log("REST", f"GET /rooms/{room_id}/messages?after_server_seq=0 (catch-up)")
    r = await client_a.get(
        f"/api/chat/rooms/{room_id}/messages",
        params={"after_server_seq": 0, "limit": 200},
    )
    assert_eq(r.status_code, 200, "catch-up 상태코드")
    messages = r.json()["messages"]
    assert len(messages) >= 1, f"최소 1건(system created) 기대, 실제 {len(messages)}"
    system_msg = next((m for m in messages if m["type"] == "system"), None)
    assert system_msg is not None, "시스템 메시지 없음"
    assert_eq(system_msg["content"]["action"], "created", "system action")
    assert_eq(system_msg["content"]["actor_id"], USER_A, "system actor")
    log("REST", "    시스템 메시지 OK — action=created, actor=A")

    return room_id


# ──────────────────── [5/6] 그룹 WS 송수신 + 읽음 ────────────────────

async def section_group_ws_and_read(group_room_id: str) -> None:
    # A, B, C 세 명 모두 WS 연결 + 방 자동 구독
    log("WS", "A/B/C 세 명 연결")
    ws_a = await connect_ws(USER_A)
    await recv_until(ws_a, "connected")
    ws_b = await connect_ws(USER_B)
    await recv_until(ws_b, "connected")
    ws_c = await connect_ws(USER_C)
    await recv_until(ws_c, "connected")

    cmid = f"cmid-grp-{int(time.time() * 1000)}"
    log("WS", f"A → 그룹방 송신 (cmid={cmid})")
    await send_json(ws_a, {
        "op": "send",
        "room_id": group_room_id,
        "client_msg_id": cmid,
        "type": "text",
        "content": "그룹 메시지 OK",
    })

    ack = await recv_until(ws_a, "message.sent")
    server_seq = ack["server_seq"]
    log("WS", f"    A ACK: server_seq={server_seq}")

    evt_b = await recv_until(ws_b, "message.new")
    assert_eq(evt_b["message"]["content"], "그룹 메시지 OK", "B content")
    evt_c = await recv_until(ws_c, "message.new")
    assert_eq(evt_c["message"]["content"], "그룹 메시지 OK", "C content")
    log("WS", "    B/C message.new 수신")

    # B 가 read op 발행
    log("WS", f"B → op=read up_to={server_seq}")
    await send_json(ws_b, {
        "op": "read",
        "room_id": group_room_id,
        "up_to_server_seq": server_seq,
    })

    ack_b = await recv_until(ws_b, "read_ack")
    assert_eq(ack_b["room_id"], group_room_id, "read_ack room_id")
    assert_eq(ack_b["up_to_server_seq"], server_seq, "read_ack seq")
    log("WS", "    B read_ack OK")

    # 나머지 세션(A, C) 에 read 이벤트 전파 — 발신 세션(B) 은 제외
    read_a = await recv_until(ws_a, "read")
    assert_eq(read_a["user_id"], USER_B, "A→read user_id")
    assert_eq(read_a["up_to_server_seq"], server_seq, "A→read seq")
    read_c = await recv_until(ws_c, "read")
    assert_eq(read_c["user_id"], USER_B, "C→read user_id")
    log("WS", "    A/C read 이벤트 수신")

    await ws_a.close()
    await ws_b.close()
    await ws_c.close()


# ──────────────────── [6/6] 편집 + 삭제 + 마스킹 ────────────────────

async def section_edit_and_delete(
    client_a: httpx.AsyncClient, direct_room_id: str,
) -> None:
    # direct 방의 A 가 보낸 텍스트 메시지 (섹션 2에서 송신된 1건)
    r = await client_a.get(
        f"/api/chat/rooms/{direct_room_id}/messages",
        params={"before_server_seq": 999999, "limit": 10},
    )
    messages = r.json()["messages"]
    target = next(m for m in messages if m["sender_id"] == USER_A and m["type"] == "text")
    msg_id = target["message_id"]

    # 편집
    log("REST", f"PATCH /messages/{msg_id} (편집)")
    r = await client_a.patch(
        f"/api/chat/messages/{msg_id}",
        json={"content": "편집된 본문"},
    )
    assert_eq(r.status_code, 200, "편집 상태코드")
    assert_eq(r.json()["content"], "편집된 본문", "편집 응답 content")

    # 히스토리 재조회 → 편집 반영
    r = await client_a.get(
        f"/api/chat/rooms/{direct_room_id}/messages",
        params={"before_server_seq": 999999, "limit": 10},
    )
    updated = next(m for m in r.json()["messages"] if m["message_id"] == msg_id)
    assert_eq(updated["content"], "편집된 본문", "히스토리에 편집 반영")
    assert updated["edited_at"] is not None, "edited_at 없음"
    log("REST", "    편집 OK + 히스토리 반영 OK")

    # 삭제
    log("REST", f"DELETE /messages/{msg_id} (soft delete)")
    r = await client_a.delete(f"/api/chat/messages/{msg_id}")
    assert_eq(r.status_code, 204, "삭제 상태코드")

    # 히스토리 재조회 → content=null 마스킹 + deleted_at 세팅
    r = await client_a.get(
        f"/api/chat/rooms/{direct_room_id}/messages",
        params={"before_server_seq": 999999, "limit": 10},
    )
    deleted = next(m for m in r.json()["messages"] if m["message_id"] == msg_id)
    assert deleted["content"] is None, f"content 마스킹 실패: {deleted['content']}"
    assert deleted["deleted_at"] is not None, "deleted_at 없음"
    log("REST", "    삭제 마스킹 OK")


# ──────────────────── 메인 ────────────────────

async def main() -> int:
    print("=" * 70)
    print("Phase 1 + Phase 2 Chat Smoke Test")
    print("=" * 70)

    async with make_client(USER_A) as client_a:
        print("\n[1/6] REST: 1:1 방 생성 + 리스트 + idempotent")
        direct_room_id = await section_direct_room(client_a)

        print("\n[2/6] WS: 1:1 방 송수신 + dedupe")
        last_seq = await section_direct_ws_send(direct_room_id)

        print("\n[3/6] REST: 1:1 방 히스토리 페이징")
        await section_direct_history(client_a, direct_room_id, last_seq)

        print("\n[4/6] REST: 그룹 방 생성 + 시스템 메시지 + catch-up")
        group_room_id = await section_group_create_and_catchup(client_a)

        print("\n[5/6] WS: 그룹 방 송수신 + 읽음 표시")
        await section_group_ws_and_read(group_room_id)

        print("\n[6/6] REST: 메시지 편집 + 삭제 + 마스킹")
        await section_edit_and_delete(client_a, direct_room_id)

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
