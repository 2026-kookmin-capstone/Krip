import asyncio
from typing import BinaryIO, List

from app.core.logger import get_logger
from app.core.object_storage import get_object_storage
from app.database.session import UnitOfWork, transactional
from app.domain.auth.repository.user import UserRepository
from app.domain.tripmate.model.tripmate_image import TripmateImage
from app.domain.tripmate.model.tripmate_post_draft import TripmatePostDraft
from app.domain.tripmate.repository.tripmate_image import TripmateImageRepository
from app.domain.tripmate.repository.tripmate_post_image import TripmatePostImageRepository
from app.domain.tripmate.service.image_reference_mutex import (
    image_reference_locked,
)
from app.util.cancellation import drain_on_cancellation
from app.util.id_generator import generate_tripmate_image_id
from app.util.storage_prefix import post_prefix


logger = get_logger("tripmate.image.service")


class TripmateImageService:
    def __init__(self, uow: UnitOfWork, image_mutex):
        self.uow = uow
        self.image_mutex = image_mutex
        self.image_repo = TripmateImageRepository()
        self.storage = get_object_storage()

    @image_reference_locked
    async def upload_image(
        self,
        user_id: str,
        file: BinaryIO,
        file_name: str,
        content_type: str,
    ) -> TripmateImage:
        image = await self._upload_to_storage(user_id, file, file_name, content_type)
        saved = await self._persist_uploads(user_id, [image])
        return saved[0]

    async def _upload_to_storage(
        self,
        user_id: str,
        file: BinaryIO,
        file_name: str,
        content_type: str,
    ) -> TripmateImage:
        """S3 업로드만 수행 — 메타데이터 저장은 _persist_uploads 가 fence 아래에서."""
        image_id = generate_tripmate_image_id()
        prefix = post_prefix(user_id)

        image_url, cancelled = await drain_on_cancellation(
            self.storage.upload_perm(file, file_name, content_type, prefix=prefix),
        )
        if cancelled:
            await self._compensate_upload(image_id, image_url)
            raise asyncio.CancelledError

        return TripmateImage(
            user_id=user_id,
            image_id=image_id,
            image_url=image_url,
        )

    async def _persist_uploads(
        self, user_id: str, images: List[TripmateImage],
    ) -> List[TripmateImage]:
        """fence 통과 시 메타데이터 저장, 거부/실패 시 업로드 전체를 보상 삭제한다."""
        try:
            saved, cancelled = await drain_on_cancellation(
                self._save_images_if_active(user_id, images),
            )
        except BaseException:
            for image in images:
                await self._compensate_upload(image.image_id, image.image_url)
            raise
        if cancelled or saved is None:
            for image in images:
                await self._compensate_upload(image.image_id, image.image_url)
            if cancelled:
                raise asyncio.CancelledError
            raise PermissionError("비활성 계정은 이미지를 업로드할 수 없습니다.")

        for image in saved:
            logger.info(
                "이미지 업로드 완료 (user_id={}, image_id={})", user_id, image.image_id,
            )
        return saved

    @transactional
    async def _save_images_if_active(
        self, user_id: str, images: List[TripmateImage],
    ) -> List[TripmateImage] | None:
        """account FOR SHARE 를 Mongo 저장 완료까지 유지해 탈퇴 commit 과 직렬화한다.

        S3 업로드(수 초) 동안 미들웨어 검사가 stale 해지는 TOCTOU 를 닫는다 —
        탈퇴가 먼저 commit 됐으면 None 을 반환해 호출측이 업로드를 보상 삭제한다.
        """
        if not await UserRepository(self._session).lock_if_active(user_id):
            return None
        return [await self.image_repo.save(image) for image in images]

    async def _compensate_upload(self, image_id: str, image_url: str) -> None:
        try:
            await drain_on_cancellation(
                self.image_repo.delete_by_image_id(image_id),
            )
            await drain_on_cancellation(self.storage.delete(image_url))
        except Exception as error:
            logger.bind(image_id=image_id, error=error).warning("업로드 보상 삭제 실패")

    @image_reference_locked
    async def upload_images(
        self,
        user_id: str,
        files: List[tuple[BinaryIO, str, str]],
    ) -> List[TripmateImage]:
        """
        이미지 여러 건 업로드

        files: [(file, file_name, content_type), ...]

        all-or-nothing: S3 업로드는 병렬, 메타데이터 저장은 전부 성공한 뒤 단일
        트랜잭션(account fence) 아래에서 일괄 수행한다. 업로드 1건이라도 실패하면
        성공분을 보상 삭제하고 원 예외를 올린다.
        """
        results = await asyncio.gather(
            *(self._upload_to_storage(user_id, file, file_name, content_type)
              for file, file_name, content_type in files),
            return_exceptions=True,
        )
        errors = [r for r in results if isinstance(r, BaseException)]
        if errors:
            succeeded = [r for r in results if isinstance(r, TripmateImage)]
            for img in succeeded:
                try:
                    await self.storage.delete(img.image_url)
                except Exception as cleanup_err:
                    logger.warning(
                        "부분 업로드 성공분 보상 삭제 실패 (image_id={}): {}",
                        img.image_id, cleanup_err,
                    )
            raise errors[0]
        return await self._persist_uploads(user_id, list(results))

    async def get_images(self, user_id: str) -> List[TripmateImage]:
        """
        유저의 전체 이미지 목록 조회 (최신순)
        """
        return await self.image_repo.find_by_user_id(user_id)

    @image_reference_locked
    @transactional
    async def delete_image(self, user_id: str, image_id: str) -> None:
        """
        이미지 단건 삭제

        1. MongoDB에서 이미지 조회 및 소유자 검증
        2. Object Storage에서 파일 삭제
        3. MongoDB에서 메타데이터 삭제
        """
        image = await self.image_repo.find_by_image_id(image_id)
        if image is None:
            raise ValueError("존재하지 않는 이미지입니다.")
        if image.user_id != user_id:
            raise PermissionError("이미지 삭제 권한이 없습니다.")

        post_image_repo = TripmatePostImageRepository(self._session)
        referenced = set(await post_image_repo.find_urls_by_user_id(user_id))
        draft = await TripmatePostDraft.find_one({"user_id": user_id})
        if draft:
            referenced |= set(draft.image_urls)
        if image.image_url in referenced:
            raise ValueError("참조 중인 이미지는 삭제할 수 없습니다.")

        await self.image_repo.delete_by_image_id(image_id)
        await self.storage.delete(image.image_url)
        logger.info("이미지 삭제 완료 (user_id={}, image_id={})", user_id, image_id)

    @image_reference_locked
    @transactional
    async def cleanup_orphaned_images(self, user_id: str) -> int:
        """
        어디에도 참조되지 않는 고아 이미지 정리

        tripmate_image(MongoDB)에 존재하지만 아래 두 곳 어디에도
        참조되지 않는 이미지를 Object Storage와 MongoDB에서 삭제한다.

        참조 소스:
          - tripmate_post_image (PostgreSQL) : 발행된 게시글 첨부 이미지
          - tripmate_post_draft (MongoDB)    : 임시저장 첨부 이미지 URL
        """
        all_images = await self.image_repo.find_by_user_id(user_id)
        if not all_images:
            return 0

        post_image_repo = TripmatePostImageRepository(self._session)
        referenced_in_posts = await post_image_repo.find_urls_by_user_id(user_id)

        draft = await TripmatePostDraft.find_one({"user_id": user_id})
        referenced_in_draft = set(draft.image_urls) if draft else set()

        referenced_urls = set(referenced_in_posts) | referenced_in_draft
        orphaned = [img for img in all_images if img.image_url not in referenced_urls]
        if not orphaned:
            return 0

        orphaned_ids = [img.image_id for img in orphaned]
        await self.image_repo.delete_by_image_ids(orphaned_ids)

        orphaned_urls = [img.image_url for img in orphaned]
        await self.storage.delete_many(orphaned_urls)

        logger.info(
            "고아 이미지 정리 완료 (user_id={}, 삭제={:d}건)",
            user_id, len(orphaned),
        )
        return len(orphaned)
