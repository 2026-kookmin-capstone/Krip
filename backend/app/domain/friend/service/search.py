from typing import Optional

from app.domain.friend.repository.search import FriendSearchRepository, PAGE_SIZE
from app.domain.friend.repository.friendship import FriendshipRepository
from app.domain.friend.model.friendship import Friendship, FriendshipStatus
from app.domain.friend.dto.search import FriendSearchData, FriendSearchListData
from app.domain.auth.model.user import User
from app.database.session import UnitOfWork, transactional
from app.util.cursor import encode_cursor


class FriendSearchService:
    """친구 추가 화면 — 이름 / user_id 부분일치로 ACTIVE 유저 검색.

    - 본인 / 탈퇴·정지·휴면 / 내가 차단 / 나를 차단한 유저는 결과에서 제외
    - 30개씩 커서 페이지네이션 (cursor = 이전 응답의 next_cursor)
    """

    def __init__(self, uow: UnitOfWork):
        self.uow = uow


    @transactional
    async def search(
        self,
        viewer_id: str,
        keyword: str,
        cursor: Optional[str] = None,
    ) -> FriendSearchListData:
        """검색 + 각 결과에 대한 viewer 기준 친구 관계 상태 매핑.

        keyword 는 양끝 공백을 제거 후 사용 — 빈 문자열은 ValueError 로 거부해
        `%  %` 패턴이 ACTIVE 유저 전체를 끌어오는 동작을 차단한다.
        """
        keyword = keyword.strip()
        if not keyword:
            raise ValueError("검색어를 입력해주세요.")

        search_repo = FriendSearchRepository(self._session)
        friendship_repo = FriendshipRepository(self._session)

        users = await search_repo.search_active_users(
            viewer_id=viewer_id,
            keyword=keyword,
            cursor=cursor,
        )

        # peer 별 friendship 을 1 쿼리로 일괄 조회 — N+1 방지
        peer_ids = [u.user_id for u in users]
        friendships = await friendship_repo.find_friendships_with(viewer_id, peer_ids)

        items = [self._to_dto(viewer_id, u, friendships.get(u.user_id)) for u in users]
        next_cursor = (
            encode_cursor(users[-1].created_at, users[-1].user_id)
            if len(users) == PAGE_SIZE else None
        )
        return FriendSearchListData(items=items, next_cursor=next_cursor)


    # ──────────────────── 내부 변환 유틸 ────────────────────

    @staticmethod
    def _to_dto(
        viewer_id: str,
        user: User,
        friendship: Optional[Friendship],
    ) -> FriendSearchData:
        if friendship is not None:
            friendship_status = friendship.status
            # is_requester 는 PENDING 일 때만 의미 — ACCEPTED / REJECTED 에선 노출 X
            is_requester = (
                friendship.requester_id == viewer_id
                if friendship.status == FriendshipStatus.PENDING
                else None
            )
        else:
            friendship_status = None
            is_requester = None

        detail = user.detail
        return FriendSearchData(
            user_id=user.user_id,
            user_name=detail.user_name,
            nationality=detail.nationality,
            travel_styles=[s.style for s in user.travel_styles],
            friendship_status=friendship_status,
            is_requester=is_requester,
            i_blocked_peer=False,  # 차단 유저는 검색 결과에서 자동 제외 → 항상 False
            profile_image_url=detail.profile_image_url,
        )
