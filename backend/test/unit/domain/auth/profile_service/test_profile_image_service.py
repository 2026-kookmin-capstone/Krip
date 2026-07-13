"""ProfileService 이미지 add/update 단위 테스트.

핵심 회귀 검증 (Bug: S3 업로드가 DB 트랜잭션을 붙잡던 문제 수정):
    - S3 업로드는 트랜잭션 밖에서 먼저 수행된다.
    - 트랜잭션(검증·DB write) 실패 시 업로드한 S3 객체를 보상 삭제해 orphan 을 막는다.
    - 성공 경로에서는 보상 삭제가 일어나지 않는다.
    - 검증(미등록·409·404) / 소유 규칙은 그대로 유지된다.
"""
import asyncio
import io
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request, UploadFile
from starlette.datastructures import Headers

from app.core.object_storage import ObjectStorage
from app.domain.auth.router.profile import add_profile_image
from app.domain.auth.service.exception import (
    ProfileImageAlreadyExistsError,
    ProfileImageNotFoundError,
    ProfileNotRegisteredError,
)


def _mk_detail(profile_image_url=None) -> SimpleNamespace:
    return SimpleNamespace(profile_image_url=profile_image_url)


_NEW_URL = "https://cdn.example.com/profile/new.jpg"
_OLD_URL = "https://cdn.example.com/profile/old.jpg"


def _upload_args():
    return dict(file=object(), file_name="p.jpg", content_type="image/jpeg")


def _actual_storage() -> ObjectStorage:
    storage = object.__new__(ObjectStorage)
    storage.bucket = "bucket"
    storage.endpoint = "https://storage.example.com"
    storage._client = MagicMock()
    return storage


@pytest.mark.unit
class TestAddProfileImage:
    async def test_router_rejects_non_image_before_public_upload(self, service):
        service.storage = _actual_storage()
        request = Request({"type": "http"})
        request.state.user_id = "USER_a"
        upload = UploadFile(
            file=io.BytesIO(b"not-an-image"),
            filename="payload.jpg",
            headers=Headers({"content-type": "image/jpeg"}),
        )

        with pytest.raises(HTTPException) as error:
            await add_profile_image(request=request, file=upload, profile_service=service)

        assert error.value.status_code == 400
        service.storage._client.upload_fileobj.assert_not_called()

    async def test_happy_path_uploads_then_writes_no_compensation(
        self, service, user_detail_repo_mock, storage_mock,
    ):
        user_detail_repo_mock.find_by_user_id.return_value = _mk_detail(None)
        storage_mock.upload_perm.return_value = _NEW_URL

        result = await service.add_profile_image(user_id="USER_a", **_upload_args())

        assert result.profile_image_url == _NEW_URL
        storage_mock.upload_perm.assert_awaited_once()
        user_detail_repo_mock.update.assert_awaited_once()
        # 성공 경로 — 보상 삭제 없음.
        storage_mock.delete.assert_not_awaited()

    async def test_already_exists_compensates_uploaded_object(
        self, service, user_detail_repo_mock, storage_mock,
    ):
        """기존 이미지 존재(409) — 업로드는 이미 되었으므로 보상 삭제로 orphan 방지."""
        user_detail_repo_mock.find_by_user_id.return_value = _mk_detail(_OLD_URL)
        storage_mock.upload_perm.return_value = _NEW_URL

        with pytest.raises(ProfileImageAlreadyExistsError):
            await service.add_profile_image(user_id="USER_a", **_upload_args())

        storage_mock.delete.assert_awaited_once_with(_NEW_URL)
        user_detail_repo_mock.update.assert_not_awaited()

    async def test_not_registered_compensates_uploaded_object(
        self, service, user_detail_repo_mock, storage_mock,
    ):
        user_detail_repo_mock.find_by_user_id.return_value = None
        storage_mock.upload_perm.return_value = _NEW_URL

        with pytest.raises(ProfileNotRegisteredError):
            await service.add_profile_image(user_id="USER_a", **_upload_args())

        storage_mock.delete.assert_awaited_once_with(_NEW_URL)

    async def test_db_failure_compensates_uploaded_object(
        self, service, user_detail_repo_mock, storage_mock,
    ):
        user_detail_repo_mock.find_by_user_id.return_value = _mk_detail(None)
        user_detail_repo_mock.update.side_effect = RuntimeError("db down")
        storage_mock.upload_perm.return_value = _NEW_URL

        async def rolled_back_profile_image(*_args):
            return None

        service._get_profile_image_url = rolled_back_profile_image

        with pytest.raises(RuntimeError):
            await service.add_profile_image(user_id="USER_a", **_upload_args())

        storage_mock.delete.assert_awaited_once_with(_NEW_URL)

    async def test_cancellation_drains_upload_and_deletes_public_object(
        self, service, user_detail_repo_mock, storage_mock,
    ):
        started = asyncio.Event()
        release = asyncio.Event()

        async def delayed_upload(*_args, **_kwargs):
            started.set()
            await release.wait()
            return _NEW_URL

        storage_mock.upload_perm.side_effect = delayed_upload
        task = asyncio.create_task(service.add_profile_image(user_id="USER_a", **_upload_args()))
        await started.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()

        with pytest.raises(asyncio.CancelledError):
            await task

        storage_mock.delete.assert_awaited_once_with(_NEW_URL)
        user_detail_repo_mock.update.assert_not_awaited()

    async def test_cancellation_during_database_attach_deletes_public_object(
        self, service, storage_mock,
    ):
        started = asyncio.Event()
        never_finish = asyncio.Event()

        async def blocked_attach(*_args):
            started.set()
            await never_finish.wait()

        storage_mock.upload_perm.return_value = _NEW_URL
        service._attach_profile_image = blocked_attach
        task = asyncio.create_task(service.add_profile_image(user_id="USER_a", **_upload_args()))
        await started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        storage_mock.delete.assert_awaited_once_with(_NEW_URL)

    async def test_commit_applied_then_cancelled_keeps_referenced_public_object(
        self, service, storage_mock,
    ):
        storage_mock.upload_perm.return_value = _NEW_URL

        async def commit_applied_then_cancelled(*_args):
            raise asyncio.CancelledError

        async def current_profile_image(*_args):
            return _NEW_URL

        service._attach_profile_image = commit_applied_then_cancelled
        service._get_profile_image_url = current_profile_image

        with pytest.raises(asyncio.CancelledError):
            await service.add_profile_image(user_id="USER_a", **_upload_args())

        storage_mock.delete.assert_not_awaited()


@pytest.mark.unit
class TestUpdateProfileImage:
    async def test_happy_path_uploads_writes_and_deletes_old(
        self, service, user_detail_repo_mock, storage_mock,
    ):
        user_detail_repo_mock.find_by_user_id.return_value = _mk_detail(_OLD_URL)
        storage_mock.upload_perm.return_value = _NEW_URL

        result = await service.update_profile_image(user_id="USER_a", **_upload_args())

        assert result.profile_image_url == _NEW_URL
        user_detail_repo_mock.update.assert_awaited_once()
        # 이전 파일만 삭제 (best-effort) — 새 파일 보상 삭제는 없음.
        storage_mock.delete.assert_awaited_once_with(_OLD_URL)

    async def test_not_found_compensates_uploaded_object(
        self, service, user_detail_repo_mock, storage_mock,
    ):
        """수정 대상 이미지 없음(404) — 새로 업로드한 파일을 보상 삭제."""
        user_detail_repo_mock.find_by_user_id.return_value = _mk_detail(None)
        storage_mock.upload_perm.return_value = _NEW_URL

        with pytest.raises(ProfileImageNotFoundError):
            await service.update_profile_image(user_id="USER_a", **_upload_args())

        storage_mock.delete.assert_awaited_once_with(_NEW_URL)
        user_detail_repo_mock.update.assert_not_awaited()

    async def test_db_failure_compensates_uploaded_object(
        self, service, user_detail_repo_mock, storage_mock,
    ):
        user_detail_repo_mock.find_by_user_id.return_value = _mk_detail(_OLD_URL)
        user_detail_repo_mock.update.side_effect = RuntimeError("db down")
        storage_mock.upload_perm.return_value = _NEW_URL

        async def rolled_back_profile_image(*_args):
            return _OLD_URL

        service._get_profile_image_url = rolled_back_profile_image

        with pytest.raises(RuntimeError):
            await service.update_profile_image(user_id="USER_a", **_upload_args())

        # 실패 시 새 파일만 보상 삭제, 이전 파일은 건드리지 않는다.
        storage_mock.delete.assert_awaited_once_with(_NEW_URL)
