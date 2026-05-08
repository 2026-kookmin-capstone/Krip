from typing import List

from app.domain.friend.repository.search_history import FriendSearchHistoryRepository
from app.domain.friend.model.search_history import FriendSearchHistory


class FriendSearchHistoryService:
    def __init__(self):
        self.search_repo = FriendSearchHistoryRepository()


    # ──────────────────── 검색어 저장 ────────────────────

    async def save_search(self, user_id: str, search_name: str) -> FriendSearchHistory:
        """
        검색어 저장

        - 동일 검색어가 이미 있으면 시간만 갱신 (최신으로)
        - 최대 10개 초과 시 가장 오래된 검색어 자동 삭제
        """
        return await self.search_repo.save(user_id=user_id, search_name=search_name)


    # ──────────────────── 검색 기록 조회 ────────────────────

    async def get_search_histories(self, user_id: str) -> List[FriendSearchHistory]:
        """
        유저의 검색 기록 조회 (최신순, 최대 10개)
        """
        return await self.search_repo.find_by_user_id(user_id)


    # ──────────────────── 검색어 단건 삭제 ────────────────────

    async def delete_search(self, user_id: str, search_name: str) -> None:
        """
        특정 검색어 1개 삭제
        """
        await self.search_repo.delete_one(user_id=user_id, search_name=search_name)


    # ──────────────────── 검색 기록 전체 삭제 ────────────────────

    async def delete_all_searches(self, user_id: str) -> None:
        """
        유저의 검색 기록 전체 삭제
        """
        await self.search_repo.delete_all_by_user_id(user_id)
