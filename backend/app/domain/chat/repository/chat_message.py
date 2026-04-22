"""MongoDB `chat_message` 리포지토리 — motor 네이티브.

beanie 대신 raw dict 을 쓰는 이유는 `app/domain/chat/model/chat_message.py` 의 모듈 주석
참조. Service 계층은 이 리포지토리의 반환 dict 을 `ChatMessageData` dataclass 로 매핑한다.
"""
from datetime import datetime
from typing import Any, Optional

from pymongo import ASCENDING, DESCENDING
from motor.motor_asyncio import AsyncIOMotorCollection, AsyncIOMotorDatabase

from app.domain.chat.model.chat_message import COLLECTION_NAME


class ChatMessageRepository:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.collection: AsyncIOMotorCollection = db[COLLECTION_NAME]


    # ──────────────────── Create ────────────────────

    async def insert(self, document: dict) -> None:
        """메시지 1건 insert.

        UNIQUE `{chat_room_id, server_seq}` 인덱스가 걸려 있어 같은 seq 중복 insert 는
        `pymongo.errors.DuplicateKeyError` 로 터진다 (C1 최종 방어선). Service 계층이
        catch 하여 `force_jump.lua` 로 재채번 + 재시도
        """
        await self.collection.insert_one(document)


    # ──────────────────── Read (단건) ────────────────────

    async def get_max_server_seq(self, chat_room_id: str) -> int:
        """방의 최대 server_seq. 없으면 0 반환 (`incr_fast` → -1 이후 복구 경로의 base).

        `recover_and_incr.lua` 호출 시 `mongo_max + SEQ_RECOVER_GAP` 을 base 로
        쓴다. 반환 0 은 "방의 진짜 첫 메시지" — 복구 경로가 `SET 0 → INCR → 1` 로 자연히
        seq=1 을 만든다.
        """
        doc = await self.collection.find_one(
            {"chat_room_id": chat_room_id},
            sort=[("server_seq", DESCENDING)],
            projection={"server_seq": 1, "_id": 0},
        )
        return int(doc["server_seq"]) if doc else 0


    # ──────────────────── Read (목록 — 히스토리 페이징) ────────────────────

    async def find_before(
        self,
        chat_room_id: str,
        before_server_seq: int,
        limit: int,
    ) -> list[dict]:
        """특정 seq **이전** 메시지를 최신순(DESC) 으로. 위로 스크롤

        `limit + 1` 개를 조회 → Service 에서 `has_more = (len == limit+1)` 판정 후
        limit 개까지만 잘라 반환.
        """
        cursor = self.collection.find(
            {
                "chat_room_id": chat_room_id,
                "server_seq": {"$lt": before_server_seq},
            },
            sort=[("server_seq", DESCENDING)],
        ).limit(limit + 1)
        return [doc async for doc in cursor]


    async def find_after(
        self,
        chat_room_id: str,
        after_server_seq: int,
        limit: int,
    ) -> list[dict]:
        """특정 seq **이후** 메시지를 과거순(ASC) 으로. 재동기화 catch-up"""
        cursor = self.collection.find(
            {
                "chat_room_id": chat_room_id,
                "server_seq": {"$gt": after_server_seq},
            },
            sort=[("server_seq", ASCENDING)],
        ).limit(limit + 1)
        return [doc async for doc in cursor]


    async def find_by_id(self, message_id: str) -> Optional[dict]:
        """단일 메시지 조회. 편집/삭제 권한 체크 용."""
        return await self.collection.find_one({"_id": message_id})


    async def find_by_ids(self, message_ids: list[str]) -> dict[str, dict]:
        """여러 `_id` 를 한 번에 조회해 `{id: doc}` 맵 반환. 방 리스트 미리보기 배치용.

        입력 리스트가 비었으면 쿼리 스킵. 결과는 dict 라 누락된 id 는 key 없음 —
        호출측이 존재 여부 분기.
        """
        if not message_ids:
            return {}
        cursor = self.collection.find({"_id": {"$in": message_ids}})
        return {doc["_id"]: doc async for doc in cursor}


    # ──────────────────── Update (편집 / 삭제) ────────────────────

    async def update_content(
        self, message_id: str, new_content: Any, edited_at: datetime,
    ) -> bool:
        """본문 교체 + `edited_at` 세팅. 편집 시 사용.

        Returns:
            실제 modify 됐으면 True. 이미 같은 content 였거나 매칭 실패면 False —
            service 단은 find_by_id 로 pre-check 하므로 False 는 동시성 race 케이스.
        """
        res = await self.collection.update_one(
            {"_id": message_id},
            {"$set": {"content": new_content, "edited_at": edited_at}},
        )
        return res.modified_count == 1


    async def soft_delete(self, message_id: str, deleted_at: datetime) -> bool:
        """soft delete — `deleted_at` 세팅 + `content=null`. 실제 row 는 보존.

        히스토리 조회 시 `deleted_at != null` 은 service 에서 content=None 으로
        마스킹되어 클라는 "삭제된 메시지입니다" 플레이스홀더 렌더.
        """
        res = await self.collection.update_one(
            {"_id": message_id},
            {"$set": {"deleted_at": deleted_at, "content": None}},
        )
        return res.modified_count == 1
