from datetime import date
from typing import List, Optional

from app.domain.tripmate.model.tripmate_post_draft import TripmatePostDraft
from app.domain.tripmate.repository.tripmate_post_draft import TripmatePostDraftRepository


class TripmatePostDraftService:
    def __init__(self):
        self.draft_repo = TripmatePostDraftRepository()

    # ──────────────────── 임시저장 저장/갱신 ────────────────────

    async def save_draft(
        self,
        user_id: str,
        title: Optional[str] = None,
        content: Optional[str] = None,
        preferred_age_min: Optional[int] = None,
        preferred_age_max: Optional[int] = None,
        preferred_gender: Optional[str] = None,
        region: Optional[str] = None,
        travel_start_date: Optional[date] = None,
        travel_end_date: Optional[date] = None,
        companion_type: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
    ) -> TripmatePostDraft:
        """
        임시저장 upsert (30초마다 프론트에서 호출)

        - 기존 임시저장이 있으면 덮어쓰기
        - 없으면 새로 생성
        """
        draft = TripmatePostDraft(
            user_id=user_id,
            title=title,
            content=content,
            preferred_age_min=preferred_age_min,
            preferred_age_max=preferred_age_max,
            preferred_gender=preferred_gender,
            region=region,
            travel_start_date=travel_start_date,
            travel_end_date=travel_end_date,
            companion_type=companion_type,
            image_urls=image_urls or [],
        )
        return await self.draft_repo.upsert(draft)

    # ──────────────────── 임시저장 조회 ────────────────────

    async def get_draft(self, user_id: str) -> Optional[TripmatePostDraft]:
        """
        유저의 임시저장 조회

        - 있으면 임시저장 데이터 반환
        - 없으면 None 반환
        """
        return await self.draft_repo.find_by_user_id(user_id)

    # ──────────────────── 임시저장 삭제 ────────────────────

    async def delete_draft(self, user_id: str) -> None:
        """
        유저의 임시저장 삭제 (게시글 발행 시 또는 수동 삭제 시 호출)
        """
        await self.draft_repo.delete_by_user_id(user_id)
