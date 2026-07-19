"""TripmateImageService — 이미지 업로드/삭제/고아 정리 e2e 통합 테스트.

Storage 만 mock — Mongo (TripmateImage / TripmatePostDraft) + RDB (TripmatePostImage) 는
실 인프라. 고아 이미지 정리의 합집합 (post 참조 ∪ draft 참조) 를 실 DB 로 검증.

검증 매트릭스:

    | 시나리오                              | 기대                                   |
    |---|---|
    | upload_image                         | Storage 호출 + Mongo metadata           |
    | delete_image 본인                    | Storage delete + Mongo row 삭제        |
    | delete_image 다른 유저               | PermissionError                         |
    | delete_image 미존재                  | ValueError                              |
    | cleanup 모두 참조됨                  | 0 반환, 외부 호출 X                     |
    | cleanup 일부 고아 (post + draft 외)  | Storage delete_many + Mongo bulk delete |
"""
import asyncio
from unittest.mock import AsyncMock

import pytest

from app.domain.tripmate.model.tripmate_image import TripmateImage
from app.domain.tripmate.model.tripmate_post_draft import TripmatePostDraft
from app.domain.tripmate.model.tripmate_post_image import TripmatePostImage
from app.domain.tripmate.service.image_reference_mutex import TripmateImageReferenceMutex


pytestmark = pytest.mark.integration


async def test_distributed_mutex_waits_across_instances_and_releases_cancelled_owner(
    tripmate_image_reference_mutex,
    engine,
):
    first = tripmate_image_reference_mutex
    second = TripmateImageReferenceMutex(engine)
    entered = asyncio.Event()

    async def enter_second():
        async with second.hold("USER_mutex"):
            entered.set()

    async with first.hold("USER_mutex"):
        waiter = asyncio.create_task(enter_second())
        await asyncio.sleep(0.05)
        assert not entered.is_set()
    await waiter
    assert entered.is_set()

    owner_started = asyncio.Event()
    owner_wait = asyncio.Event()

    async def cancelled_owner():
        async with first.hold("USER_cancelled"):
            owner_started.set()
            await owner_wait.wait()

    owner = asyncio.create_task(cancelled_owner())
    await owner_started.wait()
    owner.cancel()
    with pytest.raises(asyncio.CancelledError):
        await owner
    async with second.hold("USER_cancelled"):
        pass


class TestUploadImage:
    async def test_uploads_to_storage_and_persists_metadata(
        self, tripmate_image_service, tripmate_image_storage_mock, seed_users,
    ):
        [user_id] = await seed_users(1)

        result = await tripmate_image_service.upload_image(
            user_id=user_id, file=b"img-bytes",
            file_name="test.jpg", content_type="image/jpeg",
        )

        tripmate_image_storage_mock.upload_perm.assert_awaited_once()

        coll = TripmateImage.get_motor_collection()
        doc = await coll.find_one({"image_id": result.image_id})
        assert doc is not None
        assert doc["user_id"] == user_id
        assert doc["image_url"] == result.image_url


class TestDeleteImage:
    async def test_referenced_image_cannot_be_physically_deleted(
        self,
        tripmate_image_service,
        tripmate_image_storage_mock,
        seed_tripmate_post,
        session_factory,
    ):
        post_id, user_id = await seed_tripmate_post()
        uploaded = await tripmate_image_service.upload_image(
            user_id=user_id,
            file=b"img",
            file_name="referenced.jpg",
            content_type="image/jpeg",
        )
        async with session_factory() as session:
            session.add(TripmatePostImage(
                post_id=post_id,
                image_url=uploaded.image_url,
                image_order=0,
            ))
            await session.commit()

        with pytest.raises(ValueError, match="참조 중인 이미지"):
            await tripmate_image_service.delete_image(user_id, uploaded.image_id)

        tripmate_image_storage_mock.delete.assert_not_awaited()
        assert await TripmateImage.find_one({"image_id": uploaded.image_id}) is not None

    async def test_owner_can_delete_storage_and_metadata(
        self, tripmate_image_service, tripmate_image_storage_mock, seed_users,
    ):
        [user_id] = await seed_users(1)

        uploaded = await tripmate_image_service.upload_image(
            user_id=user_id, file=b"img", file_name="x.jpg", content_type="image/jpeg",
        )

        await tripmate_image_service.delete_image(
            user_id=user_id, image_id=uploaded.image_id,
        )

        tripmate_image_storage_mock.delete.assert_awaited_once_with(uploaded.image_url)

        coll = TripmateImage.get_motor_collection()
        assert await coll.count_documents({"image_id": uploaded.image_id}) == 0

    async def test_other_user_raises_permission_error(
        self, tripmate_image_service, seed_users,
    ):
        owner, other = await seed_users(2)

        uploaded = await tripmate_image_service.upload_image(
            user_id=owner, file=b"img", file_name="x.jpg", content_type="image/jpeg",
        )

        with pytest.raises(PermissionError):
            await tripmate_image_service.delete_image(
                user_id=other, image_id=uploaded.image_id,
            )

    async def test_missing_raises_value_error(
        self, tripmate_image_service, seed_users,
    ):
        [user_id] = await seed_users(1)

        with pytest.raises(ValueError, match="존재하지 않는"):
            await tripmate_image_service.delete_image(
                user_id=user_id, image_id="IMG_ghost",
            )


class TestCleanupOrphanedImages:
    """고아 = (post 참조 ∪ draft 참조) 의 보집합. 실 RDB + 실 Mongo 합성 검증."""

    async def test_metadata_delete_failure_does_not_delete_storage_object(
        self,
        tripmate_image_service,
        tripmate_image_storage_mock,
        seed_users,
        monkeypatch,
    ):
        [user_id] = await seed_users(1)
        image = await tripmate_image_service.upload_image(
            user_id=user_id,
            file=b"safe-order",
            file_name="safe-order.jpg",
            content_type="image/jpeg",
        )
        monkeypatch.setattr(
            tripmate_image_service.image_repo,
            "delete_by_image_ids",
            AsyncMock(side_effect=RuntimeError("mongo unavailable")),
        )

        with pytest.raises(RuntimeError, match="mongo unavailable"):
            await tripmate_image_service.cleanup_orphaned_images(user_id)

        tripmate_image_storage_mock.delete_many.assert_not_awaited()
        assert await TripmateImage.find_one({"image_id": image.image_id}) is not None

    async def test_cancellation_after_metadata_delete_cannot_create_broken_draft(
        self,
        tripmate_image_service,
        tripmate_post_draft_service,
        tripmate_image_storage_mock,
        seed_users,
    ):
        [user_id] = await seed_users(1)
        image = await tripmate_image_service.upload_image(
            user_id=user_id,
            file=b"cancel",
            file_name="cancel.jpg",
            content_type="image/jpeg",
        )
        storage_started = asyncio.Event()
        never_finish = asyncio.Event()

        async def blocked_delete_many(_urls):
            storage_started.set()
            await never_finish.wait()

        tripmate_image_storage_mock.delete_many.side_effect = blocked_delete_many
        cleanup_task = asyncio.create_task(
            tripmate_image_service.cleanup_orphaned_images(user_id),
        )
        await storage_started.wait()
        cleanup_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cleanup_task

        assert await TripmateImage.find_one({"image_id": image.image_id}) is None
        with pytest.raises(ValueError, match="본인이 업로드한 이미지"):
            await tripmate_post_draft_service.save_draft(
                user_id=user_id,
                image_urls=[image.image_url],
            )

    async def test_returns_zero_when_all_referenced(
        self, tripmate_image_service, tripmate_image_storage_mock,
        seed_users, seed_tripmate_post, session_factory,
    ):
        post_id, owner_id = await seed_tripmate_post()

        post_referenced = await tripmate_image_service.upload_image(
            user_id=owner_id, file=b"a", file_name="a.jpg", content_type="image/jpeg",
        )
        async with session_factory() as session:
            session.add(TripmatePostImage(
                post_id=post_id, image_url=post_referenced.image_url, image_order=0,
            ))
            await session.commit()

        draft_referenced = await tripmate_image_service.upload_image(
            user_id=owner_id, file=b"b", file_name="b.jpg", content_type="image/jpeg",
        )
        await TripmatePostDraft(
            user_id=owner_id, image_urls=[draft_referenced.image_url],
        ).insert()

        deleted = await tripmate_image_service.cleanup_orphaned_images(user_id=owner_id)

        assert deleted == 0
        tripmate_image_storage_mock.delete_many.assert_not_awaited()

    async def test_deletes_only_orphans_from_union(
        self, tripmate_image_service, tripmate_image_storage_mock,
        seed_users, seed_tripmate_post, session_factory,
    ):
        post_id, owner_id = await seed_tripmate_post()

        post_ref = await tripmate_image_service.upload_image(
            user_id=owner_id, file=b"p", file_name="post.jpg", content_type="image/jpeg",
        )
        draft_ref = await tripmate_image_service.upload_image(
            user_id=owner_id, file=b"d", file_name="draft.jpg", content_type="image/jpeg",
        )
        orphan1 = await tripmate_image_service.upload_image(
            user_id=owner_id, file=b"o1", file_name="o1.jpg", content_type="image/jpeg",
        )
        orphan2 = await tripmate_image_service.upload_image(
            user_id=owner_id, file=b"o2", file_name="o2.jpg", content_type="image/jpeg",
        )

        async with session_factory() as session:
            session.add(TripmatePostImage(
                post_id=post_id, image_url=post_ref.image_url, image_order=0,
            ))
            await session.commit()

        await TripmatePostDraft(
            user_id=owner_id, image_urls=[draft_ref.image_url],
        ).insert()

        deleted = await tripmate_image_service.cleanup_orphaned_images(user_id=owner_id)

        assert deleted == 2
        deleted_urls = tripmate_image_storage_mock.delete_many.await_args.args[0]
        assert set(deleted_urls) == {orphan1.image_url, orphan2.image_url}

        coll = TripmateImage.get_motor_collection()
        remaining_ids = {
            doc["image_id"] async for doc in coll.find({"user_id": owner_id})
        }
        assert remaining_ids == {post_ref.image_id, draft_ref.image_id}

    async def test_no_images_returns_zero(
        self, tripmate_image_service, seed_users,
    ):
        [user_id] = await seed_users(1)

        deleted = await tripmate_image_service.cleanup_orphaned_images(user_id=user_id)

        assert deleted == 0

    async def test_draft_writer_cannot_commit_after_cleanup_classifies_orphan(
        self,
        tripmate_image_service,
        tripmate_post_draft_service,
        tripmate_image_storage_mock,
        seed_users,
    ):
        [user_id] = await seed_users(1)
        image = await tripmate_image_service.upload_image(
            user_id=user_id,
            file=b"race",
            file_name="race.jpg",
            content_type="image/jpeg",
        )
        delete_started = asyncio.Event()
        allow_delete = asyncio.Event()

        async def blocked_delete_many(_urls):
            delete_started.set()
            await allow_delete.wait()

        tripmate_image_storage_mock.delete_many.side_effect = blocked_delete_many
        cleanup_task = asyncio.create_task(
            tripmate_image_service.cleanup_orphaned_images(user_id),
        )
        await delete_started.wait()
        save_task = asyncio.create_task(
            tripmate_post_draft_service.save_draft(
                user_id=user_id,
                title="late autosave",
                image_urls=[image.image_url],
            ),
        )

        try:
            await asyncio.sleep(0.05)
            assert not save_task.done(), "draft writer bypassed orphan cleanup barrier"
        finally:
            allow_delete.set()
            await cleanup_task

        with pytest.raises(ValueError, match="본인이 업로드한 이미지"):
            await save_task
        assert await TripmatePostDraft.find_one({"user_id": user_id}) is None

    async def test_cleanup_waits_for_inflight_draft_writer_and_preserves_image(
        self,
        tripmate_image_service,
        tripmate_post_draft_service,
        tripmate_image_storage_mock,
        seed_users,
    ):
        [user_id] = await seed_users(1)
        image = await tripmate_image_service.upload_image(
            user_id=user_id,
            file=b"race",
            file_name="writer-first.jpg",
            content_type="image/jpeg",
        )
        writer_started = asyncio.Event()
        allow_writer = asyncio.Event()
        real_upsert = tripmate_post_draft_service.draft_repo.upsert

        async def blocked_upsert(draft):
            writer_started.set()
            await allow_writer.wait()
            return await real_upsert(draft)

        tripmate_post_draft_service.draft_repo.upsert = blocked_upsert
        save_task = asyncio.create_task(
            tripmate_post_draft_service.save_draft(
                user_id=user_id,
                title="writer wins",
                image_urls=[image.image_url],
            ),
        )
        await writer_started.wait()
        cleanup_task = asyncio.create_task(
            tripmate_image_service.cleanup_orphaned_images(user_id),
        )

        try:
            await asyncio.sleep(0.05)
            assert not cleanup_task.done(), "cleanup bypassed draft writer barrier"
        finally:
            allow_writer.set()

        await save_task
        assert await cleanup_task == 0
        tripmate_image_storage_mock.delete_many.assert_not_awaited()
        assert await TripmateImage.find_one({"image_id": image.image_id}) is not None
