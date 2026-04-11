from typing import List, Optional

from app.domain.tripmate.model.tripmate_image import TripmateImage


class TripmateImageRepository:

    # ──────────────────── Create ────────────────────

    async def save(self, image: TripmateImage) -> TripmateImage:
        """이미지 단건 저장"""
        await image.insert()
        return image

    # ──────────────────── Read ────────────────────

    async def find_by_user_id(self, user_id: str) -> list[TripmateImage]:
        """유저의 전체 이미지 목록 조회 (최신순)"""
        return await TripmateImage.find(
            {"user_id": user_id}
        ).sort("-timestamp").to_list()

    async def find_by_image_id(self, image_id: str) -> Optional[TripmateImage]:
        """이미지 ID로 단건 조회"""
        return await TripmateImage.find_one({"image_id": image_id})

    # ──────────────────── Delete ────────────────────

    async def delete_by_image_id(self, image_id: str) -> None:
        """이미지 단건 삭제"""
        image = await TripmateImage.find_one({"image_id": image_id})
        if image:
            await image.delete()

    async def delete_by_image_ids(self, image_ids: List[str]) -> None:
        """이미지 ID 목록으로 일괄 삭제"""
        if not image_ids:
            return
        await TripmateImage.find({"image_id": {"$in": image_ids}}).delete()

    async def delete_by_urls(self, image_urls: List[str]) -> None:
        """이미지 URL 목록으로 일괄 삭제"""
        if not image_urls:
            return
        await TripmateImage.find({"image_url": {"$in": image_urls}}).delete()

    async def delete_by_user_id(self, user_id: str) -> None:
        """유저의 전체 이미지 삭제"""
        await TripmateImage.find({"user_id": user_id}).delete()
