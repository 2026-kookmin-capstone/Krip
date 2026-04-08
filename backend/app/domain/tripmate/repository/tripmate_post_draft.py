from typing import Optional
from datetime import datetime, timezone

from pymongo import ReturnDocument

from app.domain.tripmate.model.tripmate_post_draft import TripmatePostDraft


class TripmatePostDraftRepository:

    # ──────────────────── Upsert (저장/갱신) ────────────────────

    async def upsert(self, draft: TripmatePostDraft) -> TripmatePostDraft:
        """임시저장 upsert — single atomic operation"""
        doc = draft.model_dump(exclude={"id"})
        doc["updated_at"] = datetime.now(timezone.utc)

        result = await TripmatePostDraft.get_motor_collection().find_one_and_update(
            {"user_id": draft.user_id},
            {"$set": doc},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        return TripmatePostDraft.model_validate(result)


    # ──────────────────── Read ────────────────────

    async def find_by_user_id(self, user_id: str) -> Optional[TripmatePostDraft]:
        """유저의 임시저장 조회"""
        return await TripmatePostDraft.find_one({"user_id": user_id})


    # ──────────────────── Delete ────────────────────

    async def delete_by_user_id(self, user_id: str) -> None:
        """유저의 임시저장 삭제 (게시글 발행 시 또는 수동 삭제 시 호출)"""
        draft = await TripmatePostDraft.find_one({"user_id": user_id})
        if draft:
            await draft.delete()
