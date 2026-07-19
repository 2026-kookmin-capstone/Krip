from app.database.session import UnitOfWork, transactional
from app.domain.auth.model.user import UserStatus
from app.domain.auth.repository.user import UserRepository
from app.domain.friend.dto.friend_detail import FriendDetailData
from app.domain.friend.repository.friendship import FriendshipRepository
from app.domain.friend.repository.user_block import UserBlockRepository


class UserNotFoundError(ValueError):
    """URL 경로로 지정된 유저가 DB 에 존재하지 않음 — 라우터에서 404 로 매핑."""


class FriendDetailService:
    """상대 유저 기본 프로필 + 내 기준 관계 상태 조회."""

    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    @transactional
    async def get_friend_detail(self, viewer_id: str, peer_id: str) -> FriendDetailData:
        """
        1. 상대 유저 존재 + 2차 회원가입 완료 검증
        2. 차단 관계 (양방향) 조회 — 상대가 나를 차단했으면 검색과 동일하게 404 로 숨김
        3. friendship (방향 무관) 조회
        4. DTO 조립 — 민감 정보(auth_provider, status, email, phone_number) 제외

        예외:
            UserNotFoundError: 유저가 DB 에 존재하지 않음 / 상대가 나를 차단 → 라우터 404
            ValueError: 유저는 존재하지만 2차 회원가입 미완료 → 라우터 400
        """

        user_repo = UserRepository(self._session)
        friendship_repo = FriendshipRepository(self._session)
        block_repo = UserBlockRepository(self._session)

        peer = await user_repo.find_by_id_with_profile(peer_id)
        # 탈퇴 진행 중/정지 계정도 404 — 검색(ACTIVE 필터)과 동일하게 존재를 숨긴다.
        if peer is None or peer.status != UserStatus.ACTIVE:
            raise UserNotFoundError("존재하지 않는 유저입니다.")

        # 차단 검사(404)를 2차 가입 미완료(400) 검사보다 먼저 — 400 이 차단 유저의 존재를 노출하지 않게.
        blocks = await block_repo.find_blocks_between(viewer_id, peer_id)
        if any(b.blocker_id == peer_id for b in blocks):
            raise UserNotFoundError("존재하지 않는 유저입니다.")
        i_blocked = any(b.blocker_id == viewer_id for b in blocks)

        if peer.detail is None:
            raise ValueError("2차 회원가입이 완료되지 않은 유저입니다.")

        friendship = await friendship_repo.find_between(viewer_id, peer_id)

        if friendship is not None:
            friendship_id = friendship.friendship_id
            friendship_status = friendship.status
            is_requester = friendship.requester_id == viewer_id
        else:
            friendship_id = None
            friendship_status = None
            is_requester = None

        return FriendDetailData(
            user_id=peer.user_id,
            user_name=peer.detail.user_name,
            age=peer.detail.age,
            gender=peer.detail.gender,
            nationality=peer.detail.nationality,
            travel_styles=[s.style for s in peer.travel_styles],
            friendship_id=friendship_id,
            friendship_status=friendship_status,
            is_requester=is_requester,
            i_blocked_peer=i_blocked,
            profile_image_url=peer.detail.profile_image_url,
        )
