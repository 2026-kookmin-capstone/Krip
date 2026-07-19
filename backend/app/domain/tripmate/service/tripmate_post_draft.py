from datetime import date
from typing import List, Optional

from app.domain.tripmate.model.tripmate_post_draft import TripmatePostDraft
from app.domain.tripmate.repository.tripmate_image import TripmateImageRepository
from app.domain.tripmate.repository.tripmate_post_draft import TripmatePostDraftRepository
from app.domain.tripmate.service.image_reference_mutex import (
    image_reference_locked,
)


class TripmatePostDraftService:
    def __init__(self, image_mutex):
        self.image_mutex = image_mutex
        self.draft_repo = TripmatePostDraftRepository()
        self.image_repo = TripmateImageRepository()

    @image_reference_locked
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

        - 전체 스냅샷 계약: 클라가 매 호출 폼 전체 상태를 보내므로 문서 통째 덮어쓰기가
          올바른 시맨틱이다 (생략 필드 = 비운 필드). 부분 병합으로 "고치지" 말 것.
        - 기존 임시저장이 있으면 덮어쓰기, 없으면 새로 생성
        """
        normalized_image_urls = image_urls or []
        if normalized_image_urls:
            owned = await self.image_repo.find_owned_urls(user_id, normalized_image_urls)
            if any(url not in owned for url in normalized_image_urls):
                raise ValueError("본인이 업로드한 이미지만 첨부할 수 있습니다.")

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
            image_urls=normalized_image_urls,
        )
        return await self.draft_repo.upsert(draft)

    async def get_draft(self, user_id: str) -> Optional[TripmatePostDraft]:
        """
        유저의 임시저장 조회

        - 있으면 임시저장 데이터 반환
        - 없으면 None 반환
        """
        return await self.draft_repo.find_by_user_id(user_id)

    @image_reference_locked
    async def delete_draft(self, user_id: str) -> None:
        """
        유저의 임시저장 삭제 (게시글 발행 시 또는 수동 삭제 시 호출)
        """
        await self.draft_repo.delete_by_user_id(user_id)
