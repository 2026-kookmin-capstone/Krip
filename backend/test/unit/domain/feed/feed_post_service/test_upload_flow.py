"""upload_post 흐름 회귀 테스트 — 정규화 통합 + 실패 시 cleanup.

happy path 전체 (실 Pillow + 실 S3 + 실 INSERT) 는 통합 테스트 영역. 본 파일은:
    - thumbnail 결과를 stub 으로 주입해 service 흐름만 검증
    - 빈/공백 caption 이 INSERT 까지 None 으로 흘러가는지 (정규화 통합)
    - S3 upload 실패 시 `delete_by_prefix` 가 호출되는지 (cleanup 보장)
    - INSERT 실패 시에도 cleanup 호출되는지 (S3 → DB 순서의 cleanup 단일 진입점)

`@transactional` 가 실제 commit 까지 호출하므로 mock_session 의 close/commit 도 정상 동작.
"""
import asyncio
import threading
from types import SimpleNamespace

import pytest

from app.core.object_storage import ObjectStorage
from app.domain.feed.dto.image import ProcessedFeedImage, ProcessedVariant
from app.domain.feed.model.feed_post import FeedVisibility


def _stub_processed() -> ProcessedFeedImage:
    """Pillow 처리 결과 stub — bytes 는 식별 가능한 sentinel 만 담음."""
    return ProcessedFeedImage(
        original=ProcessedVariant(b"orig-bytes", "image/jpeg", "jpg"),
        small=ProcessedVariant(b"small-bytes", "image/jpeg", "jpg"),
        medium=ProcessedVariant(b"medium-bytes", "image/jpeg", "jpg"),
    )


@pytest.fixture
def stub_thumbnail(monkeypatch):
    """thumbnail.process_feed_image 를 stub 으로 치환 — Pillow 디코딩 회피."""
    monkeypatch.setattr(
        "app.domain.feed.service.feed_post.process_feed_image",
        lambda _bytes: _stub_processed(),
    )


@pytest.mark.unit
class TestUploadCaptionNormalization:
    async def test_empty_caption_normalized_to_none_in_insert(
        self, service, repo_mock, storage_mock, stub_thumbnail,
    ):
        """POST 진입점도 PATCH 와 동일 정규화 — 빈 문자열 → None 으로 INSERT."""
        storage_mock.upload_to_key.return_value = "https://x/url"

        result = await service.upload_post(
            user_id="USER_a",
            file_bytes=b"x",
            visibility=FeedVisibility.PUBLIC,
            caption="",
        )
        assert result.caption is None
        saved_post = repo_mock.save.await_args.args[0]
        assert saved_post.caption is None

    async def test_whitespace_caption_normalized(
        self, service, repo_mock, storage_mock, stub_thumbnail,
    ):
        storage_mock.upload_to_key.return_value = "https://x/url"
        result = await service.upload_post(
            user_id="USER_a", file_bytes=b"x",
            visibility=FeedVisibility.PUBLIC, caption="   \n  ",
        )
        assert result.caption is None

    async def test_non_blank_caption_passes_through(
        self, service, repo_mock, storage_mock, stub_thumbnail,
    ):
        storage_mock.upload_to_key.return_value = "https://x/url"
        result = await service.upload_post(
            user_id="USER_a", file_bytes=b"x",
            visibility=FeedVisibility.PUBLIC, caption="안녕",
        )
        assert result.caption == "안녕"

    async def test_new_post_has_zero_counts(
        self, service, repo_mock, storage_mock, stub_thumbnail,
    ):
        """신규 업로드 직후엔 좋아요/댓글 항상 0 — service 가 reload 없이 0 으로 합성."""
        storage_mock.upload_to_key.return_value = "https://x/url"
        result = await service.upload_post(
            user_id="USER_a", file_bytes=b"x",
            visibility=FeedVisibility.PUBLIC, caption="hi",
        )
        assert result.like_count == 0
        assert result.comment_count == 0

    async def test_new_post_is_liked_false(
        self, service, repo_mock, storage_mock, stub_thumbnail,
    ):
        """신규 업로드 직후엔 본인이 자기 글에 아직 좋아요 안 눌렀으므로 항상 False —
        service 가 reload 없이 False 로 합성 (인스타 동치).
        """
        storage_mock.upload_to_key.return_value = "https://x/url"
        result = await service.upload_post(
            user_id="USER_a", file_bytes=b"x",
            visibility=FeedVisibility.PUBLIC, caption="hi",
        )
        assert result.is_liked is False


@pytest.mark.unit
class TestUploadCleanupOnFailure:
    async def test_s3_upload_failure_triggers_prefix_cleanup(
        self, service, repo_mock, storage_mock, stub_thumbnail,
    ):
        """S3 가 부분/전부 실패해도 외부 try 가 prefix 통째 삭제로 정리."""
        storage_mock.upload_to_key.side_effect = RuntimeError("S3 down")

        with pytest.raises(RuntimeError, match="S3 down"):
            await service.upload_post(
                user_id="USER_a", file_bytes=b"x",
                visibility=FeedVisibility.PUBLIC, caption="hi",
            )
        storage_mock.delete_by_prefix.assert_awaited_once()
        called_prefix = storage_mock.delete_by_prefix.await_args.args[0]
        assert called_prefix.startswith("USER_a/feed/FDP_")
        repo_mock.save.assert_not_called()

    async def test_insert_failure_triggers_cleanup(
        self, service, repo_mock, storage_mock, stub_thumbnail,
    ):
        """S3 성공 + INSERT 실패 시에도 cleanup 단일 진입점 동작."""
        storage_mock.upload_to_key.return_value = "https://x/url"
        repo_mock.save.side_effect = RuntimeError("DB down")

        with pytest.raises(RuntimeError, match="DB down"):
            await service.upload_post(
                user_id="USER_a", file_bytes=b"x",
                visibility=FeedVisibility.PUBLIC, caption="hi",
            )
        storage_mock.delete_by_prefix.assert_awaited_once()

    async def test_commit_applied_then_cancelled_preserves_referenced_upload(
        self, service, mock_session, storage_mock, stub_thumbnail,
    ):
        storage_mock.upload_to_key.return_value = "https://x/url"
        mock_session.get.return_value = SimpleNamespace(
            original_url="https://x/url",
            thumbnail_small_url="https://x/url",
            thumbnail_medium_url="https://x/url",
        )

        async def committed_then_cancelled(**_kwargs):
            raise asyncio.CancelledError

        service._insert_post = committed_then_cancelled

        with pytest.raises(asyncio.CancelledError):
            await service.upload_post(
                user_id="USER_a", file_bytes=b"x",
                visibility=FeedVisibility.PUBLIC, caption="hi",
            )

        storage_mock.delete_by_prefix.assert_not_awaited()

    async def test_insert_reconciliation_failure_preserves_upload(
        self, service, mock_session, repo_mock, storage_mock, stub_thumbnail,
    ):
        storage_mock.upload_to_key.return_value = "https://x/url"
        repo_mock.save.side_effect = RuntimeError("commit outcome unknown")
        mock_session.get.side_effect = RuntimeError("database unavailable")

        with pytest.raises(RuntimeError, match="commit outcome unknown"):
            await service.upload_post(
                user_id="USER_a", file_bytes=b"x",
                visibility=FeedVisibility.PUBLIC, caption="hi",
            )

        storage_mock.delete_by_prefix.assert_not_awaited()

    async def test_cleanup_failure_does_not_mask_original_error(
        self, service, repo_mock, storage_mock, stub_thumbnail,
    ):
        """cleanup 자체가 실패해도 원 예외는 그대로 propagate (best-effort + log)."""
        storage_mock.upload_to_key.side_effect = RuntimeError("S3 down")
        storage_mock.delete_by_prefix.side_effect = RuntimeError("cleanup also down")

        with pytest.raises(RuntimeError, match="S3 down"):
            await service.upload_post(
                user_id="USER_a", file_bytes=b"x",
                visibility=FeedVisibility.PUBLIC, caption="hi",
            )

    async def test_cancelled_upload_still_triggers_cleanup_and_repropagates(
        self, service, repo_mock, storage_mock, stub_thumbnail,
    ):
        """클라 끊김/셧다운으로 업로드 태스크가 취소돼도 S3 고아를 남기지 않는다.

        CancelledError 는 BaseException 이라 과거 `except Exception` 을 그대로 통과해
        cleanup 이 스킵됐다. 이제는 cleanup 을 태우고 CancelledError 를 그대로 재던진다
        (취소 신호를 삼키지 않음).
        """
        storage_mock.upload_to_key.side_effect = asyncio.CancelledError()

        with pytest.raises(asyncio.CancelledError):
            await service.upload_post(
                user_id="USER_a", file_bytes=b"x",
                visibility=FeedVisibility.PUBLIC, caption="hi",
            )
        storage_mock.delete_by_prefix.assert_awaited_once()
        called_prefix = storage_mock.delete_by_prefix.await_args.args[0]
        assert called_prefix.startswith("USER_a/feed/FDP_")

    async def test_cancellation_drains_accepted_uploads_before_prefix_cleanup(
        self, service, repo_mock, storage_mock, stub_thumbnail,
    ):
        started = asyncio.Event()
        release = asyncio.Event()
        workers: list[asyncio.Task[str]] = []
        objects: set[str] = set()
        cleanup_started = asyncio.Event()
        accepted = 0

        async def upload_finishes_after_coroutine_cancellation(
            _data, *, prefix, filename, content_type,
        ):
            nonlocal accepted
            accepted += 1
            if accepted == 3:
                started.set()

            async def worker() -> str:
                await release.wait()
                objects.add(filename)
                return f"https://storage/{prefix}/{filename}"

            worker_task = asyncio.create_task(worker())
            workers.append(worker_task)
            return await asyncio.shield(worker_task)

        async def delete_prefix(_prefix: str) -> int:
            cleanup_started.set()
            deleted = len(objects)
            objects.clear()
            return deleted

        storage_mock.upload_to_key.side_effect = upload_finishes_after_coroutine_cancellation
        storage_mock.delete_by_prefix.side_effect = delete_prefix
        task = asyncio.create_task(service.upload_post(
            user_id="USER_a",
            file_bytes=b"x",
            visibility=FeedVisibility.PUBLIC,
            caption="cancelled",
        ))
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        cleanup_crossed_uploads = False
        try:
            await asyncio.wait_for(cleanup_started.wait(), timeout=0.1)
            cleanup_crossed_uploads = True
        except TimeoutError:
            pass
        finally:
            release.set()

        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.gather(*workers)

        assert not cleanup_crossed_uploads
        assert objects == set()
        storage_mock.delete_by_prefix.assert_awaited_once()
        repo_mock.save.assert_not_awaited()


@pytest.mark.unit
class TestImageProcessingCancellation:
    async def test_cancelled_processing_holds_semaphore_until_thread_finishes(
        self, service, storage_mock, monkeypatch,
    ):
        from app.domain.feed.service import feed_post as feed_post_module

        first_started = threading.Event()
        second_started = threading.Event()
        release = threading.Event()
        calls = 0
        calls_lock = threading.Lock()

        def blocking_process(_data):
            nonlocal calls
            with calls_lock:
                calls += 1
                current = calls
            (first_started if current == 1 else second_started).set()
            assert release.wait(timeout=2)
            return _stub_processed()

        monkeypatch.setattr(feed_post_module, "process_feed_image", blocking_process)
        monkeypatch.setattr(feed_post_module, "_image_semaphore", asyncio.Semaphore(1))
        monkeypatch.setattr(
            feed_post_module, "_image_semaphore_loop", asyncio.get_running_loop(),
        )
        storage_mock.upload_to_key.return_value = "https://x/url"

        first = asyncio.create_task(service.upload_post(
            user_id="USER_a", file_bytes=b"first",
            visibility=FeedVisibility.PUBLIC,
        ))
        assert await asyncio.to_thread(first_started.wait, 1)
        first.cancel()
        for task in asyncio.all_tasks():
            if task is not asyncio.current_task() and "to_thread" in repr(task.get_coro()):
                task.cancel()
        second = asyncio.create_task(service.upload_post(
            user_id="USER_a", file_bytes=b"second",
            visibility=FeedVisibility.PUBLIC,
        ))

        try:
            assert not await asyncio.to_thread(second_started.wait, 0.1)
        finally:
            release.set()

        with pytest.raises(asyncio.CancelledError):
            await first
        await second

    async def test_forced_all_task_cancellation_drains_upload_threads_before_cleanup(
        self, service, stub_thumbnail,
    ):
        storage = object.__new__(ObjectStorage)
        storage.endpoint = "https://storage.example.com"
        storage.bucket = "bucket"
        started = threading.Event()
        release = threading.Event()
        cleanup_started = asyncio.Event()
        objects: set[str] = set()
        accepted = 0
        lock = threading.Lock()

        def blocking_upload(file, key: str, content_type: str) -> str:
            nonlocal accepted
            del file, content_type
            with lock:
                accepted += 1
                if accepted == 3:
                    started.set()
            assert release.wait(timeout=2)
            objects.add(key)
            return f"https://storage.example.com/bucket/{key}"

        async def delete_prefix(prefix: str) -> int:
            del prefix
            cleanup_started.set()
            objects.clear()
            return 0

        storage._upload = blocking_upload
        storage.delete_by_prefix = delete_prefix
        service.storage = storage
        request = asyncio.create_task(service.upload_post(
            user_id="USER_a", file_bytes=b"image",
            visibility=FeedVisibility.PUBLIC,
        ))
        assert await asyncio.to_thread(started.wait, 1)

        owned_names = ("upload_post", "upload_variants", "upload_to_key", "to_thread")
        for task in asyncio.all_tasks():
            if task is asyncio.current_task():
                continue
            if task is request or any(name in repr(task.get_coro()) for name in owned_names):
                task.cancel()

        cleanup_crossed_uploads = False
        try:
            await asyncio.wait_for(cleanup_started.wait(), timeout=0.1)
            cleanup_crossed_uploads = True
        except TimeoutError:
            pass
        finally:
            release.set()

        with pytest.raises(asyncio.CancelledError):
            await request
        assert not cleanup_crossed_uploads
        assert objects == set()
