"""TripmatePostService — 게시글 CRUD 단위 테스트.

검증 대상 (메서드별 핵심 분기 위주):
    - `create_post`: INSERT + image attach + draft 정리 (best-effort) + detail snapshot
    - `get_post`: 단건 조회 + 미존재 가드
    - `get_posts` / `search_posts`: 페이지네이션 + next_cursor 합성
    - `update_post`: 권한 + 이미지 차집합 cleanup (best-effort)
    - `delete_post`: 권한 + 이미지 cleanup (best-effort) + 알림 cascade 안 함
    - `toggle_display`: 권한 + 토글
"""
from test.unit.domain.tripmate.tripmate_post_service.model_factory import (
    TripmatePostFactory,
    make_post_image,
)
import pytest
from datetime import date

from app.domain.tripmate.repository.tripmate_post import PAGE_SIZE
from app.domain.tripmate.model.tripmate_post import CompanionType, PreferredGender


# 게시글 생성/수정 공통 필드 — 테스트가 관심 없는 필드는 여기서 채우고 관심 필드만 override.
def _post_fields(**overrides):
    fields = dict(
        title="t",
        content="c",
        preferred_age_min=20,
        preferred_age_max=30,
        preferred_gender=PreferredGender.ANY,
        region="제주",
        travel_start_date=date(2026, 6, 1),
        travel_end_date=date(2026, 6, 5),
        companion_type=CompanionType.FRIEND,
    )
    fields.update(overrides)
    return fields


# ──────────────────────────────────────────────────────────────────
# create_post
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestCreatePost:
    """Tests for TripmatePostService.create_post."""

    async def test_saves_post_and_returns_dto(
        self, service, post_repo_mock, image_repo_mock, detail_repo_mock,
    ):
        """기본 INSERT — post / image_repo 호출 + DTO 반환."""
        from types import SimpleNamespace
        detail_repo_mock.find_by_user_id.return_value = SimpleNamespace(
            profile_image_url="https://img/p.jpg",
        )

        result = await service.create_post(
            user_id="USER_a",
            title="제주 동행",
            content="6/1 ~ 6/5",
            preferred_age_min=20,
            preferred_age_max=30,
            preferred_gender=PreferredGender.ANY,
            region="제주",
            travel_start_date=date(2026, 6, 1),
            travel_end_date=date(2026, 6, 5),
            companion_type=CompanionType.FRIEND,
            image_urls=None,
        )

        post_repo_mock.save.assert_awaited_once()
        image_repo_mock.save_all.assert_not_awaited()  # 이미지 없음
        assert result.title == "제주 동행"
        assert result.image_urls == []
        assert result.profile_image_url == "https://img/p.jpg"


    async def test_attaches_images_when_provided(
        self, service, image_repo_mock,
    ):
        """이미지 URL 리스트 → 순서 보존하여 image_repo.save_all 호출."""
        await service.create_post(
            user_id="USER_a",
            title="t",
            content="c",
            preferred_age_min=20,
            preferred_age_max=30,
            preferred_gender=PreferredGender.ANY,
            region="r",
            travel_start_date=date(2026, 6, 1),
            travel_end_date=date(2026, 6, 5),
            companion_type=CompanionType.FRIEND,
            image_urls=["https://img/1", "https://img/2"],
        )

        image_repo_mock.save_all.assert_awaited_once()
        saved = image_repo_mock.save_all.await_args.args[0]
        assert [img.image_order for img in saved] == [0, 1]
        assert [img.image_url for img in saved] == ["https://img/1", "https://img/2"]


    async def test_draft_delete_failure_is_swallowed(
        self, service, draft_service_mock,
    ):
        """draft 삭제 실패해도 게시글 생성은 성공 — best-effort."""
        draft_service_mock.delete_draft.side_effect = RuntimeError("draft missing")

        # raise 없이 정상 종료
        await service.create_post(
            user_id="USER_a",
            title="t",
            content="c",
            preferred_age_min=20,
            preferred_age_max=30,
            preferred_gender=PreferredGender.ANY,
            region="r",
            travel_start_date=date(2026, 6, 1),
            travel_end_date=date(2026, 6, 5),
            companion_type=CompanionType.FRIEND,
        )


    async def test_profile_image_url_none_when_detail_missing(
        self, service, detail_repo_mock,
    ):
        """detail 결손 → profile_image_url=None fallback."""
        detail_repo_mock.find_by_user_id.return_value = None

        result = await service.create_post(
            user_id="USER_a",
            title="t",
            content="c",
            preferred_age_min=20,
            preferred_age_max=30,
            preferred_gender=PreferredGender.ANY,
            region="r",
            travel_start_date=date(2026, 6, 1),
            travel_end_date=date(2026, 6, 5),
            companion_type=CompanionType.FRIEND,
        )

        assert result.profile_image_url is None


# ──────────────────────────────────────────────────────────────────
# get_post — 단건 조회
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestGetPost:
    """Tests for TripmatePostService.get_post."""

    async def test_returns_dto_when_post_exists(
        self, service, post_repo_mock,
    ):
        post = TripmatePostFactory.create(
            post_id="TMP_x", user_id="USER_owner", title="제주",
            like_count=5, is_liked=True,
            images=[make_post_image("https://img/1", 0), make_post_image("https://img/2", 1)],
        )
        post_repo_mock.find_by_id_with_detail.return_value = post

        result = await service.get_post(post_id="TMP_x", user_id="USER_viewer")

        assert result.post_id == "TMP_x"
        assert result.title == "제주"
        assert result.like_count == 5
        assert result.is_liked is True
        assert result.image_urls == ["https://img/1", "https://img/2"]


    async def test_orders_images_by_image_order(
        self, service, post_repo_mock,
    ):
        """image_order asc 정렬 — image_urls 순서 검증."""
        post = TripmatePostFactory.create(
            images=[
                make_post_image("https://img/3", 2),
                make_post_image("https://img/1", 0),
                make_post_image("https://img/2", 1),
            ],
        )
        post_repo_mock.find_by_id_with_detail.return_value = post

        result = await service.get_post(post_id=post.post_id)

        assert result.image_urls == ["https://img/1", "https://img/2", "https://img/3"]


    async def test_raises_when_not_found(self, service, post_repo_mock):
        post_repo_mock.find_by_id_with_detail.return_value = None

        with pytest.raises(ValueError, match="존재하지 않는"):
            await service.get_post(post_id="TMP_x")


# ──────────────────────────────────────────────────────────────────
# get_posts / search_posts — 페이지네이션
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestGetPosts:
    """Tests for TripmatePostService.get_posts (목록 페이지네이션)."""

    async def test_returns_empty_when_none(self, service, post_repo_mock):
        post_repo_mock.find_all_displayed.return_value = []

        result = await service.get_posts()

        assert result.posts == []
        assert result.next_cursor is None


    async def test_no_next_cursor_when_under_page_size(
        self, service, post_repo_mock,
    ):
        post_repo_mock.find_all_displayed.return_value = [
            TripmatePostFactory.create() for _ in range(PAGE_SIZE - 1)
        ]

        result = await service.get_posts()

        assert len(result.posts) == PAGE_SIZE - 1
        assert result.next_cursor is None


    async def test_next_cursor_is_last_post_id_when_exact_page_size(
        self, service, post_repo_mock,
    ):
        """딱 PAGE_SIZE 만큼 fetch → 마지막 post_id 가 next_cursor."""
        posts = [TripmatePostFactory.create(post_id=f"TMP_{i:03d}") for i in range(PAGE_SIZE)]
        post_repo_mock.find_all_displayed.return_value = posts

        result = await service.get_posts()

        assert result.next_cursor == posts[-1].post_id


@pytest.mark.unit
class TestSearchPosts:
    """Tests for TripmatePostService.search_posts."""

    async def test_passes_keyword_and_cursor_to_repo(
        self, service, post_repo_mock,
    ):
        post_repo_mock.search.return_value = []

        await service.search_posts(
            keyword="제주", cursor="TMP_xxx", user_id="USER_viewer",
        )

        post_repo_mock.search.assert_awaited_once_with(
            "제주", "TMP_xxx", user_id="USER_viewer",
        )


# ──────────────────────────────────────────────────────────────────
# update_post — 권한 + 이미지 차집합 cleanup
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestUpdatePost:
    """Tests for TripmatePostService.update_post."""

    async def _do_update(self, service, post_id, user_id, image_urls=None):
        return await service.update_post(
            post_id=post_id,
            user_id=user_id,
            title="updated",
            content="updated content",
            preferred_age_min=20,
            preferred_age_max=30,
            preferred_gender=PreferredGender.ANY,
            region="제주",
            travel_start_date=date(2026, 6, 1),
            travel_end_date=date(2026, 6, 5),
            companion_type=CompanionType.FRIEND,
            image_urls=image_urls,
        )


    async def test_raises_when_not_found(self, service, post_repo_mock):
        post_repo_mock.find_by_id.return_value = None

        with pytest.raises(ValueError, match="존재하지 않는"):
            await self._do_update(service, "TMP_x", "USER_a")


    async def test_raises_when_not_author(self, service, post_repo_mock):
        post = TripmatePostFactory.create(user_id="USER_owner")
        post_repo_mock.find_by_id.return_value = post

        with pytest.raises(PermissionError, match="권한"):
            await self._do_update(service, post.post_id, "USER_other")


    async def test_cleans_only_removed_images(
        self, service, post_repo_mock, image_repo_mock,
        storage_mock, mongo_image_repo_mock,
    ):
        """차집합(old - new) 만 storage / mongo 정리 — 유지되는 이미지는 건드리지 않음."""
        post = TripmatePostFactory.create(user_id="USER_a")
        post_repo_mock.find_by_id.return_value = post
        post_repo_mock.find_by_id_with_detail.return_value = post  # 응답용 reload
        image_repo_mock.find_by_post_id.return_value = [
            make_post_image("https://img/old1"),
            make_post_image("https://img/keep"),
        ]

        await self._do_update(
            service, post.post_id, "USER_a",
            image_urls=["https://img/keep", "https://img/new"],
        )

        # 제거된 것만 cleanup (old1)
        storage_mock.delete_many.assert_awaited_once()
        removed = storage_mock.delete_many.await_args.args[0]
        assert removed == ["https://img/old1"]
        mongo_image_repo_mock.delete_by_urls.assert_awaited_once_with(["https://img/old1"])


    async def test_image_cleanup_failure_is_swallowed(
        self, service, post_repo_mock, image_repo_mock, storage_mock,
    ):
        """제거 이미지 cleanup 실패 → swallow + 로그, RDB 변경은 유지."""
        post = TripmatePostFactory.create(user_id="USER_a")
        post_repo_mock.find_by_id.return_value = post
        post_repo_mock.find_by_id_with_detail.return_value = post
        image_repo_mock.find_by_post_id.return_value = [make_post_image("https://img/old")]
        storage_mock.delete_many.side_effect = RuntimeError("s3 down")

        # raise 없이 정상 종료
        await self._do_update(service, post.post_id, "USER_a", image_urls=None)


# ──────────────────────────────────────────────────────────────────
# delete_post — 권한 + 이미지 cleanup
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestDeletePost:
    """Tests for TripmatePostService.delete_post.

    인박스 cascade — 게시글 삭제 시 해당 게시글의 알림을 soft hide (display=False).
    `_delete_post_tx` 커밋 후 `inbox_service.cascade_post_deleted` 호출을 검증한다.
    실패 swallow / TargetType 매칭 등의 best-effort 동작은 InboxService 단위 테스트가 담당.
    """

    async def test_raises_when_not_found(self, service, post_repo_mock):
        post_repo_mock.find_by_id.return_value = None

        with pytest.raises(ValueError, match="존재하지 않는"):
            await service.delete_post(post_id="TMP_x", user_id="USER_a")


    async def test_raises_when_not_author(self, service, post_repo_mock):
        post = TripmatePostFactory.create(user_id="USER_owner")
        post_repo_mock.find_by_id.return_value = post

        with pytest.raises(PermissionError, match="권한"):
            await service.delete_post(post_id=post.post_id, user_id="USER_other")


    async def test_deletes_post_and_cleans_images(
        self, service, post_repo_mock, image_repo_mock,
        storage_mock, mongo_image_repo_mock, inbox_service_mock,
    ):
        from app.domain.notification.model.inbox import TargetType

        post = TripmatePostFactory.create(user_id="USER_a")
        post_repo_mock.find_by_id.return_value = post
        image_repo_mock.find_by_post_id.return_value = [
            make_post_image("https://img/1"),
            make_post_image("https://img/2"),
        ]

        await service.delete_post(post_id=post.post_id, user_id="USER_a")

        post_repo_mock.delete.assert_awaited_once_with(post)
        storage_mock.delete_many.assert_awaited_once_with(
            ["https://img/1", "https://img/2"],
        )
        mongo_image_repo_mock.delete_by_urls.assert_awaited_once_with(
            ["https://img/1", "https://img/2"],
        )
        inbox_service_mock.cascade_post_deleted.assert_awaited_once_with(
            target_type=TargetType.TRIPMATE_POST,
            target_id=post.post_id,
        )


    async def test_no_cascade_when_unauthorized(
        self, service, post_repo_mock, inbox_service_mock,
    ):
        """권한 실패 → 트랜잭션 raise → outer 가 cascade 호출 안 함 (RDB 롤백 race 회피 contract)."""
        post = TripmatePostFactory.create(user_id="USER_owner")
        post_repo_mock.find_by_id.return_value = post

        with pytest.raises(PermissionError):
            await service.delete_post(post_id=post.post_id, user_id="USER_other")

        inbox_service_mock.cascade_post_deleted.assert_not_awaited()


    async def test_no_image_cleanup_when_no_images(
        self, service, post_repo_mock, image_repo_mock, storage_mock,
    ):
        post = TripmatePostFactory.create(user_id="USER_a")
        post_repo_mock.find_by_id.return_value = post
        image_repo_mock.find_by_post_id.return_value = []

        await service.delete_post(post_id=post.post_id, user_id="USER_a")

        storage_mock.delete_many.assert_not_awaited()


    async def test_image_cleanup_failure_is_swallowed(
        self, service, post_repo_mock, image_repo_mock, storage_mock,
    ):
        """이미지 정리 실패 → swallow. RDB 게시글 삭제는 이미 commit."""
        post = TripmatePostFactory.create(user_id="USER_a")
        post_repo_mock.find_by_id.return_value = post
        image_repo_mock.find_by_post_id.return_value = [make_post_image("https://img/1")]
        storage_mock.delete_many.side_effect = RuntimeError("s3 down")

        # raise 없이 정상 종료
        await service.delete_post(post_id=post.post_id, user_id="USER_a")
        post_repo_mock.delete.assert_awaited_once()


# ──────────────────────────────────────────────────────────────────
# toggle_display
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestToggleDisplay:
    """Tests for TripmatePostService.toggle_display."""

    async def test_toggles_true_to_false(self, service, post_repo_mock):
        post = TripmatePostFactory.create(user_id="USER_a", is_displayed=True)
        post_repo_mock.find_by_id.return_value = post

        result = await service.toggle_display(post_id=post.post_id, user_id="USER_a")

        assert result is False
        assert post.is_displayed is False


    async def test_toggles_false_to_true(self, service, post_repo_mock):
        post = TripmatePostFactory.create(user_id="USER_a", is_displayed=False)
        post_repo_mock.find_by_id.return_value = post

        result = await service.toggle_display(post_id=post.post_id, user_id="USER_a")

        assert result is True
        assert post.is_displayed is True


    async def test_raises_when_not_found(self, service, post_repo_mock):
        post_repo_mock.find_by_id.return_value = None

        with pytest.raises(ValueError, match="존재하지 않는"):
            await service.toggle_display(post_id="TMP_x", user_id="USER_a")


    async def test_raises_when_not_author(self, service, post_repo_mock):
        post = TripmatePostFactory.create(user_id="USER_owner")
        post_repo_mock.find_by_id.return_value = post

        with pytest.raises(PermissionError, match="권한"):
            await service.toggle_display(post_id=post.post_id, user_id="USER_other")


# ──────────────────────────────────────────────────────────────────
# 이미지 소유권 가드 (IDOR 방지) — _assert_images_owned
#   클라이언트가 보낸 URL 을 그대로 신뢰하면 타 유저 이미지를 첨부한 뒤 게시글을
#   수정/삭제해 남의 Object Storage 파일을 지울 수 있다. 업로드 소유 목록과 대조.
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestImageOwnershipGuard:
    """create_post / update_post 첨부 이미지의 업로더 소유권 검증."""

    async def test_create_rejects_unowned_image(
        self, service, post_repo_mock, mongo_image_repo_mock,
    ):
        """본인이 업로드하지 않은 URL 첨부 → ValueError, INSERT 자체가 일어나지 않음."""
        mongo_image_repo_mock.find_owned_urls.side_effect = lambda uid, urls: set()

        with pytest.raises(ValueError, match="본인이 업로드한 이미지만"):
            await service.create_post(
                user_id="USER_a",
                image_urls=["https://img/stolen"],
                **_post_fields(),
            )

        post_repo_mock.save.assert_not_awaited()


    async def test_create_rejects_when_partially_unowned(
        self, service, post_repo_mock, mongo_image_repo_mock,
    ):
        """일부만 본인 소유여도 (하나라도 남의 것이면) 전체 거부."""
        mongo_image_repo_mock.find_owned_urls.side_effect = (
            lambda uid, urls: {"https://img/mine"}
        )

        with pytest.raises(ValueError, match="본인이 업로드한 이미지만"):
            await service.create_post(
                user_id="USER_a",
                image_urls=["https://img/mine", "https://img/stolen"],
                **_post_fields(),
            )

        post_repo_mock.save.assert_not_awaited()


    async def test_create_allows_when_all_owned(
        self, service, post_repo_mock, image_repo_mock, mongo_image_repo_mock,
    ):
        """전부 본인 소유 → 정상 저장 + 소유권 조회가 (user_id, urls) 로 호출됨."""
        urls = ["https://img/1", "https://img/2"]

        await service.create_post(
            user_id="USER_a", image_urls=urls, **_post_fields(),
        )

        post_repo_mock.save.assert_awaited_once()
        image_repo_mock.save_all.assert_awaited_once()
        mongo_image_repo_mock.find_owned_urls.assert_awaited_once()
        assert mongo_image_repo_mock.find_owned_urls.await_args.args == ("USER_a", urls)


    async def test_create_skips_check_when_no_images(
        self, service, mongo_image_repo_mock,
    ):
        """이미지 없음 → 소유권 조회 skip (불필요한 Mongo 왕복 방지)."""
        await service.create_post(
            user_id="USER_a", image_urls=None, **_post_fields(),
        )

        mongo_image_repo_mock.find_owned_urls.assert_not_awaited()


    async def test_update_rejects_unowned_image(
        self, service, post_repo_mock, mongo_image_repo_mock,
    ):
        """수정 시 남의 이미지 첨부 → ValueError. 필드 UPDATE / 응답 reload 도 일어나지 않음."""
        post = TripmatePostFactory.create(user_id="USER_a", title="original")
        post_repo_mock.find_by_id.return_value = post
        mongo_image_repo_mock.find_owned_urls.side_effect = lambda uid, urls: set()

        with pytest.raises(ValueError, match="본인이 업로드한 이미지만"):
            await service.update_post(
                post_id=post.post_id,
                user_id="USER_a",
                image_urls=["https://img/stolen"],
                **_post_fields(title="updated"),
            )

        post_repo_mock.update.assert_not_awaited()
        post_repo_mock.find_by_id_with_detail.assert_not_awaited()
        assert post.title == "original"  # 거부 전 mutation 없음


    async def test_update_ownership_checked_after_permission(
        self, service, post_repo_mock, mongo_image_repo_mock,
    ):
        """작성자 아님 → 소유권 조회까지 가기 전에 PermissionError (권한 우선)."""
        post = TripmatePostFactory.create(user_id="USER_owner")
        post_repo_mock.find_by_id.return_value = post

        with pytest.raises(PermissionError, match="권한"):
            await service.update_post(
                post_id=post.post_id,
                user_id="USER_other",
                image_urls=["https://img/whatever"],
                **_post_fields(),
            )

        mongo_image_repo_mock.find_owned_urls.assert_not_awaited()


# ──────────────────────────────────────────────────────────────────
# 고아 이미지 보호 — _filter_unreferenced_urls
#   같은 이미지를 여러 게시글/임시저장이 공유할 때, 한 곳을 지워도 다른 곳이 깨지지
#   않도록 실제로 아무 데서도 참조되지 않는 URL 만 물리 삭제한다.
# ──────────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestOrphanImageProtection:
    """update_post / delete_post 의 참조 인식(reference-aware) 이미지 정리."""

    async def test_update_keeps_image_referenced_by_other_post(
        self, service, post_repo_mock, image_repo_mock,
        storage_mock, mongo_image_repo_mock,
    ):
        """제거된 이미지가 유저의 다른 게시글에서 여전히 참조 → 물리 삭제 안 함."""
        post = TripmatePostFactory.create(user_id="USER_a")
        post_repo_mock.find_by_id.return_value = post
        post_repo_mock.find_by_id_with_detail.return_value = post
        image_repo_mock.find_by_post_id.return_value = [
            make_post_image("https://img/shared"),
        ]
        # 이 게시글에서는 빠졌지만 다른 게시글이 여전히 참조 중
        image_repo_mock.find_urls_by_user_id.return_value = ["https://img/shared"]

        await service.update_post(
            post_id=post.post_id, user_id="USER_a",
            image_urls=["https://img/new"], **_post_fields(),
        )

        storage_mock.delete_many.assert_not_awaited()
        mongo_image_repo_mock.delete_by_urls.assert_not_awaited()


    async def test_update_keeps_image_referenced_by_draft(
        self, service, post_repo_mock, image_repo_mock,
        storage_mock, mongo_image_repo_mock, draft_find_one_mock,
    ):
        """제거된 이미지가 임시저장(draft)에서 참조 중 → 물리 삭제 안 함."""
        from types import SimpleNamespace

        post = TripmatePostFactory.create(user_id="USER_a")
        post_repo_mock.find_by_id.return_value = post
        post_repo_mock.find_by_id_with_detail.return_value = post
        image_repo_mock.find_by_post_id.return_value = [
            make_post_image("https://img/shared"),
        ]
        image_repo_mock.find_urls_by_user_id.return_value = []  # 다른 게시글엔 없음
        draft_find_one_mock.return_value = SimpleNamespace(
            image_urls=["https://img/shared"],
        )

        await service.update_post(
            post_id=post.post_id, user_id="USER_a",
            image_urls=["https://img/new"], **_post_fields(),
        )

        storage_mock.delete_many.assert_not_awaited()
        mongo_image_repo_mock.delete_by_urls.assert_not_awaited()


    async def test_update_deletes_only_truly_orphaned(
        self, service, post_repo_mock, image_repo_mock,
        storage_mock, mongo_image_repo_mock,
    ):
        """제거 이미지 중 어디에서도 참조 안 되는 것만 물리 삭제 (부분 삭제)."""
        post = TripmatePostFactory.create(user_id="USER_a")
        post_repo_mock.find_by_id.return_value = post
        post_repo_mock.find_by_id_with_detail.return_value = post
        image_repo_mock.find_by_post_id.return_value = [
            make_post_image("https://img/shared"),
            make_post_image("https://img/orphan"),
        ]
        image_repo_mock.find_urls_by_user_id.return_value = ["https://img/shared"]

        await service.update_post(
            post_id=post.post_id, user_id="USER_a",
            image_urls=[], **_post_fields(),  # 둘 다 제거
        )

        storage_mock.delete_many.assert_awaited_once_with(["https://img/orphan"])
        mongo_image_repo_mock.delete_by_urls.assert_awaited_once_with(["https://img/orphan"])


    async def test_delete_keeps_image_referenced_by_other_post(
        self, service, post_repo_mock, image_repo_mock,
        storage_mock, mongo_image_repo_mock, mock_session,
    ):
        """삭제 시에도 다른 게시글이 참조하는 이미지는 물리 삭제 안 함 + CASCADE flush 수행."""
        post = TripmatePostFactory.create(user_id="USER_a")
        post_repo_mock.find_by_id.return_value = post
        image_repo_mock.find_by_post_id.return_value = [
            make_post_image("https://img/shared"),
        ]
        image_repo_mock.find_urls_by_user_id.return_value = ["https://img/shared"]

        await service.delete_post(post_id=post.post_id, user_id="USER_a")

        mock_session.flush.assert_awaited()  # CASCADE 반영
        storage_mock.delete_many.assert_not_awaited()
        mongo_image_repo_mock.delete_by_urls.assert_not_awaited()


    async def test_delete_flushes_before_reference_check(
        self, service, post_repo_mock, image_repo_mock,
        storage_mock, mock_session,
    ):
        """flush(post 삭제 CASCADE) 가 참조 검사(find_urls_by_user_id) 보다 먼저 실행돼야
        이 게시글의 이미지가 '참조됨' 으로 오판되지 않는다 — 호출 순서 검증."""
        from unittest.mock import Mock

        post = TripmatePostFactory.create(user_id="USER_a")
        post_repo_mock.find_by_id.return_value = post
        image_repo_mock.find_by_post_id.return_value = [make_post_image("https://img/1")]
        image_repo_mock.find_urls_by_user_id.return_value = []  # flush 후엔 고아

        order = Mock()
        order.attach_mock(mock_session.flush, "flush")
        order.attach_mock(image_repo_mock.find_urls_by_user_id, "find_urls")

        await service.delete_post(post_id=post.post_id, user_id="USER_a")

        names = [c[0] for c in order.mock_calls]
        assert "flush" in names and "find_urls" in names
        assert names.index("flush") < names.index("find_urls")
        # 고아이므로 실제 물리 삭제까지 진행
        storage_mock.delete_many.assert_awaited_once_with(["https://img/1"])
