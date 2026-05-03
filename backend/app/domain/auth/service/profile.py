from typing import BinaryIO

from app.util.storage_prefix import profile_prefix
from app.domain.auth.repository.user import UserRepository
from app.domain.auth.repository.user_detail_inform import UserDetailInformRepository
from app.domain.auth.dto.profile import ProfileData, ProfileImageData
from app.domain.auth.service.exception import (
    ProfileNotRegisteredError,
    ProfileImageAlreadyExistsError,
    ProfileImageNotFoundError,
)
from app.database.session import UnitOfWork, transactional
from app.core.object_storage import get_object_storage
from app.core.logger import get_logger


logger = get_logger("auth.profile.service")


class ProfileService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow
        self.storage = get_object_storage()


    @transactional
    async def get_my_profile(self, user_id: str) -> ProfileData:
        """유저 프로필 전체 정보 조회"""
        user_repo = UserRepository(self._session)

        user = await user_repo.find_by_id_with_profile(user_id)
        if user is None:
            raise ValueError("존재하지 않는 유저입니다.")
        if user.detail is None:
            raise ProfileNotRegisteredError("2차 회원가입이 완료되지 않은 유저입니다.")

        return ProfileData(
            user_id=user.user_id,
            auth_provider=user.auth_provider,
            status=user.status,
            email=user.detail.email,
            user_name=user.detail.user_name,
            phone_number=user.detail.phone_number,
            age=user.detail.age,
            gender=user.detail.gender,
            nationality=user.detail.nationality,
            travel_styles=[s.style for s in user.travel_styles],
            profile_image_url=user.detail.profile_image_url,
            notification_muted=user.notification_muted is True,
        )


    # ──────────────────── 프로필 이미지 추가 ────────────────────

    @transactional
    async def add_profile_image(
        self,
        user_id: str,
        file: BinaryIO,
        file_name: str,
        content_type: str,
    ) -> ProfileImageData:
        """
        프로필 이미지 추가 (유저당 1장 정책)

        1. detail 존재 검증
        2. 기존 이미지가 있으면 409 (수정은 PUT 사용)
        3. Object Storage 업로드
        4. DB 컬럼 갱신

        DB 갱신 실패 시 rollback 되며, 업로드된 S3 파일은 orphan 으로 남는다.
        탈퇴 시 prefix 단위로 정리되므로 영구 누적은 아니다.
        """
        detail_repo = UserDetailInformRepository(self._session)

        detail = await detail_repo.find_by_user_id(user_id)
        if detail is None:
            raise ProfileNotRegisteredError("2차 회원가입이 완료되지 않은 유저입니다.")
        if detail.profile_image_url is not None:
            raise ProfileImageAlreadyExistsError("이미 프로필 이미지가 존재합니다. 수정은 PUT 으로 요청해주세요.")

        new_url = await self.storage.upload_perm(
            file, file_name, content_type, prefix=profile_prefix(user_id),
        )

        detail.profile_image_url = new_url
        await detail_repo.update(detail)
        logger.info("프로필 이미지 추가 완료 (user_id={})", user_id)

        return ProfileImageData(profile_image_url=new_url)


    # ──────────────────── 프로필 이미지 수정 ────────────────────

    async def update_profile_image(
        self,
        user_id: str,
        file: BinaryIO,
        file_name: str,
        content_type: str,
    ) -> ProfileImageData:
        """
        프로필 이미지 수정 (기존 1장 → 새 1장)

        1. (트랜잭션) detail 검증 + S3 업로드 + DB 갱신 → 이전 URL 반환
        2. (트랜잭션 밖) 이전 S3 파일 삭제 (best-effort)

        S3 삭제를 트랜잭션 안에서 하면 commit 실패 시 broken link 위험 → 분리.
        """
        new_url, old_url = await self._replace_profile_image(
            user_id, file, file_name, content_type,
        )

        try:
            await self.storage.delete(old_url)
        except Exception as e:
            logger.warning("이전 프로필 이미지 삭제 실패 — orphan 파일 잔존 (user_id={}): {}", user_id, e)

        logger.info("프로필 이미지 수정 완료 (user_id={})", user_id)
        return ProfileImageData(profile_image_url=new_url)


    @transactional
    async def _replace_profile_image(
        self,
        user_id: str,
        file: BinaryIO,
        file_name: str,
        content_type: str,
    ) -> tuple[str, str]:
        """수정 흐름의 트랜잭션 부분 — (new_url, old_url) 반환."""
        detail_repo = UserDetailInformRepository(self._session)

        detail = await detail_repo.find_by_user_id(user_id)
        if detail is None:
            raise ProfileNotRegisteredError("2차 회원가입이 완료되지 않은 유저입니다.")
        if detail.profile_image_url is None:
            raise ProfileImageNotFoundError("수정할 프로필 이미지가 없습니다. 먼저 POST 로 추가해주세요.")

        old_url = detail.profile_image_url

        new_url = await self.storage.upload_perm(
            file, file_name, content_type, prefix=profile_prefix(user_id),
        )

        detail.profile_image_url = new_url
        await detail_repo.update(detail)

        return new_url, old_url


    # ──────────────────── 프로필 이미지 삭제 ────────────────────

    async def delete_profile_image(self, user_id: str) -> None:
        """
        프로필 이미지 삭제

        1. (트랜잭션) detail 검증 + DB 컬럼 NULL 처리 → 이전 URL 반환
        2. (트랜잭션 밖) S3 파일 삭제 (best-effort)
        """
        old_url = await self._null_profile_image(user_id)

        try:
            await self.storage.delete(old_url)
        except Exception as e:
            logger.warning("프로필 이미지 파일 삭제 실패 — orphan 파일 잔존 (user_id={}): {}", user_id, e)

        logger.info("프로필 이미지 삭제 완료 (user_id={})", user_id)


    @transactional
    async def _null_profile_image(self, user_id: str) -> str:
        """삭제 흐름의 트랜잭션 부분 — 이전 URL 반환."""
        detail_repo = UserDetailInformRepository(self._session)

        detail = await detail_repo.find_by_user_id(user_id)
        if detail is None:
            raise ProfileNotRegisteredError("2차 회원가입이 완료되지 않은 유저입니다.")
        if detail.profile_image_url is None:
            raise ProfileImageNotFoundError("삭제할 프로필 이미지가 없습니다.")

        old_url = detail.profile_image_url
        detail.profile_image_url = None
        await detail_repo.update(detail)

        return old_url
