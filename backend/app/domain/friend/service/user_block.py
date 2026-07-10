from typing import Optional

from sqlalchemy.exc import IntegrityError

from app.database.session import UnitOfWork, transactional
from app.domain.auth.model.user import User
from app.domain.auth.repository.user import UserRepository
from app.domain.friend.dto.friendship import FriendPeerData
from app.domain.friend.dto.user_block import UserBlockData, UserBlockListData
from app.domain.friend.model.user_block import UserBlock
from app.domain.friend.repository.friendship import FriendshipRepository
from app.domain.friend.repository.user_block import PAGE_SIZE, UserBlockRepository
from app.util.cursor import encode_cursor


class UserBlockService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow

    # ──────────────────── 차단 ────────────────────

    async def block_user(self, user_id: str, target_user_id: str) -> UserBlockData:
        """유저 차단 — 송신 권한은 RDB pair-lock 으로 판정하므로 캐시 훅 없음."""
        return await self._block_user_tx(user_id, target_user_id)

    @transactional
    async def _block_user_tx(self, user_id: str, target_user_id: str) -> UserBlockData:
        """
        1. 자기 자신 차단 불가
        2. 대상 유저 존재 + 2차 회원가입 완료 검증
        3. 이미 차단한 상태면 에러
        4. 두 유저 간의 friendship 관계는 모두 정리
           (PENDING/ACCEPTED는 즉시 끊어야 하고, REJECTED도 삭제해 재요청 경로가 깔끔하게 새로 시작되도록)
        5. (blocker=user_id, blocked=target) row 저장
        """
        if user_id == target_user_id:
            raise ValueError("자기 자신을 차단할 수 없습니다.")

        block_repo = UserBlockRepository(self._session)
        friendship_repo = FriendshipRepository(self._session)
        user_repo = UserRepository(self._session)

        # pair advisory lock (read 보다 먼저) — friendship 정리~block 삽입을 원자화해
        # 차단-친구요청 TOCTOU 를 차단.
        await friendship_repo.acquire_pair_lock(user_id, target_user_id)

        target = await user_repo.find_by_id_with_profile(target_user_id)
        if target is None:
            raise ValueError("존재하지 않는 유저입니다.")
        # 2차 미완료(detail=None)는 400 으로 거부(프로필 구성 불가). 정상 UI 로는 노출 안 돼 도달 불가.
        if target.detail is None:
            raise ValueError("2차 회원가입이 완료되지 않은 유저입니다.")

        if await block_repo.has_blocker_blocked(user_id, target_user_id):
            raise ValueError("이미 차단한 유저입니다.")

        # 두 유저 간 friendship row가 있다면 제거 (방향 무관)
        friendship = await friendship_repo.find_between(user_id, target_user_id)
        if friendship is not None:
            await friendship_repo.delete(friendship)
            await self._session.flush()

        block = UserBlock(blocker_id=user_id, blocked_id=target_user_id)
        try:
            # SAVEPOINT 로 INSERT 만 감싸서 동시 차단 경합을 uq_user_block_pair 위반으로 감지
            async with self._session.begin_nested():
                await block_repo.save(block)
        except IntegrityError:
            existing_block = await block_repo.find_by_pair(user_id, target_user_id)
            if existing_block is not None:
                raise ValueError("이미 차단한 유저입니다.")
            raise ValueError("차단을 처리하지 못했습니다. 잠시 후 다시 시도해주세요.")

        return self._to_dto(block, target)

    # ──────────────────── 차단 해제 ────────────────────

    async def unblock_user(self, user_id: str, target_user_id: str) -> None:
        """차단 해제 — 송신 권한은 RDB pair-lock 으로 판정하므로 캐시 훅 없음."""
        await self._unblock_user_tx(user_id, target_user_id)

    @transactional
    async def _unblock_user_tx(self, user_id: str, target_user_id: str) -> None:
        """(blocker=user_id, blocked=target) 레코드 삭제."""
        block_repo = UserBlockRepository(self._session)

        await block_repo.acquire_pair_lock(user_id, target_user_id)

        block = await block_repo.find_by_pair(blocker_id=user_id, blocked_id=target_user_id)
        if block is None:
            raise ValueError("차단 상태가 아닙니다.")

        await block_repo.delete(block)

    # ──────────────────── 목록 조회 ────────────────────

    @transactional
    async def get_blocked_users(self, user_id: str, cursor: Optional[str] = None) -> UserBlockListData:
        """내가 차단한 유저 목록"""
        block_repo = UserBlockRepository(self._session)
        items = await block_repo.find_blocks_by_user(user_id, cursor)
        return self._to_list_dto(items)

    # ──────────────────── 내부 변환 유틸 ────────────────────

    @staticmethod
    def _to_peer_dto(user: User) -> FriendPeerData:
        detail = user.detail
        return FriendPeerData(
            user_id=user.user_id,
            user_name=detail.user_name,
            age=detail.age,
            gender=detail.gender,
            nationality=detail.nationality,
            profile_image_url=detail.profile_image_url,
        )

    @classmethod
    def _to_dto(cls, block: UserBlock, blocked_user: User) -> UserBlockData:
        return UserBlockData(
            block_id=block.block_id,
            blocked=cls._to_peer_dto(blocked_user),
            created_at=block.created_at,
        )

    def _to_list_dto(self, items: list[UserBlock]) -> UserBlockListData:
        dtos = [self._to_dto(b, b.blocked) for b in items]
        next_cursor = (
            encode_cursor(items[-1].created_at, items[-1].block_id)
            if len(items) == PAGE_SIZE else None
        )
        return UserBlockListData(items=dtos, next_cursor=next_cursor)
