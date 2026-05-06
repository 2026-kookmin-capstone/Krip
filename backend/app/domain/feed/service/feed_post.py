"""피드 게시물 서비스 — 본인 피드 CRUD.

업로드 흐름 (S3 → 트랜잭션 두 단계):
    1. (트랜잭션 밖) Pillow 처리 — 잘못된 이미지 fast-fail (ValueError → 400)
    2. (트랜잭션 밖) S3 병렬 업로드 3건 — DB 커넥션 미점유. wall time ~300~800ms.
    3. (트랜잭션) PG INSERT 만 — 커넥션 점유 ~5~20ms.
    4. 어떤 단계에서든 실패 시 prefix cleanup (`delete_by_prefix`) 후 재던짐.

S3 를 트랜잭션 밖으로 빼는 이유 — S3 와 INSERT 사이에 정합성 의존이 0 (post_id 는 트랜잭션
밖에서 발급, INSERT 가 single-row, 외부 read 의존 없음). 안에 두면 S3 wall time 만큼 DB
커넥션이 idle hold 되어 풀 압박 + idle-in-transaction 경보. 정합성 손해 없이 풀 점유 시간 30~50× 감소.

cleanup 보장 — public 메서드의 wrapper try 가 commit 실패까지 catch:
    - S3 업로드 실패 / PG INSERT 실패 / commit 실패 모두 동일 cleanup path
    - `delete_by_prefix` 가 prefix 하위 partial / full 객체 모두 한 번에 정리
    - cleanup 자체는 best-effort (실패해도 swallow + log) — orphan S3 객체는 운영 도구로 정리

삭제 순서 — DB 먼저, S3 best-effort (auth/profile 패턴):
    - DB row 가 살아있는 채로 S3 가 먼저 사라지면 broken URL 노출
    - DB 가 먼저 지워지면 orphan S3 가 남을 수 있지만 사용자에겐 invisible

가시성 / 친구·차단 합성 (다른 유저 피드 조회) — `get_user_feed` 가 진입점.
viewer↔owner 차단은 `FeedBlockedError` 로 진입 자체 차단, 친구/비친구는 `visibility`
부분집합으로 좁혀 단일 SQL 로 페이지네이션. 규칙은 `service/visibility.py::can_view`
가 단일 진입점.
"""
from typing import Optional
import asyncio

from app.util.id_generator import generate_feed_post_id
from app.util.storage_prefix import feed_post_prefix
from app.domain.feed.service.thumbnail import process_feed_image
from app.domain.feed.service.visibility import can_view
from app.domain.feed.service.exception import FeedBlockedError, FeedNotFoundError
from app.domain.feed.repository.feed_post import FeedPostRepository, PAGE_SIZE
from app.domain.feed.model.feed_post import FeedPost, FeedVisibility
from app.domain.feed.dto.feed_post import FeedPostData, FeedPostListData
from app.domain.friend.model.friendship import FriendshipStatus
from app.domain.friend.repository.friendship import FriendshipRepository
from app.domain.friend.repository.user_block import UserBlockRepository
from app.database.session import UnitOfWork, transactional
from app.core.object_storage import get_object_storage
from app.core.logger import get_logger


logger = get_logger("feed.post.service")


def _normalize_caption(caption: Optional[str]) -> Optional[str]:
    """캡션 입력 정규화 — 빈 문자열 / 공백만 → None.

    "캡션 없음" 의 DB 표현을 null 단일로 통일한다. 프론트가 textarea 를 비우면 자연스럽게
    "" 가 들어오는 패턴을 흡수해 빈 문자열 row 가 생기지 않게 함. POST(업로드) / PATCH(수정)
    두 진입점에서 동일하게 호출되어 origin 과 무관하게 같은 정규화 규칙이 적용된다.

    비-빈 캡션의 leading/trailing 공백은 의도된 입력일 수 있어 보존 (over-trimming 회피).
    """
    if caption is None or not caption.strip():
        return None
    return caption


class FeedPostService:
    def __init__(self, uow: UnitOfWork):
        self.uow = uow
        self.storage = get_object_storage()


    # ──────────────────── 업로드 ────────────────────

    async def upload_post(
        self,
        user_id: str,
        file_bytes: bytes,
        visibility: FeedVisibility,
        caption: Optional[str] = None,
    ) -> FeedPostData:
        """피드 게시물 업로드 (S3 → 트랜잭션 두 단계).

        실패 처리:
            - Pillow 디코딩 실패 → ValueError (S3/DB 미접근)
            - S3 / DB / commit 실패 → S3 prefix cleanup 후 재던짐
        """
        # Step 1 — Pillow (CPU-bound, thread pool. 트랜잭션 밖 fast-fail).
        # ValueError 면 라우터에서 400 으로 매핑, S3/DB 자원 자체를 안 건드림.
        processed = await asyncio.to_thread(process_feed_image, file_bytes)

        # post_id / prefix 발급은 트랜잭션 밖에서 — 어떤 실패 경로에서도 cleanup 호출 가능하도록.
        post_id = generate_feed_post_id()
        prefix = feed_post_prefix(user_id, post_id)

        # 빈 문자열 / 공백만 → None 정규화 (PATCH 와 동일 규칙).
        caption = _normalize_caption(caption)

        # Step 2 — S3 + INSERT. 외부 try 가 cleanup 단일 진입점.
        # S3 는 트랜잭션 밖에서 수행 (DB 커넥션 미점유), INSERT 만 트랜잭션 안.
        # `_insert_post` 의 commit 은 `__aexit__` 에서 일어나므로 commit 실패도 본 try 가 catch.
        try:
            # ── S3 병렬 업로드 — DB 커넥션 미점유. asyncio.gather 로 wall time 1/3 단축.
            original_url, small_url, medium_url = await asyncio.gather(
                self.storage.upload_to_key(
                    processed.original.data,
                    prefix=prefix,
                    filename=f"original.{processed.original.file_ext}",
                    content_type=processed.original.content_type,
                ),
                self.storage.upload_to_key(
                    processed.small.data,
                    prefix=prefix,
                    filename=f"small.{processed.small.file_ext}",
                    content_type=processed.small.content_type,
                ),
                self.storage.upload_to_key(
                    processed.medium.data,
                    prefix=prefix,
                    filename=f"medium.{processed.medium.file_ext}",
                    content_type=processed.medium.content_type,
                ),
            )

            # ── PG INSERT — 트랜잭션은 여기서만 열림. 커넥션 점유 ~5~20ms.
            post = await self._insert_post(
                user_id=user_id,
                post_id=post_id,
                visibility=visibility,
                caption=caption,
                original_url=original_url,
                small_url=small_url,
                medium_url=medium_url,
            )
        except Exception:
            await self._safe_cleanup(prefix)
            raise

        return self._to_dto(post)


    @transactional
    async def _insert_post(
        self,
        *,
        user_id: str,
        post_id: str,
        visibility: FeedVisibility,
        caption: Optional[str],
        original_url: str,
        small_url: str,
        medium_url: str,
    ) -> FeedPost:
        """피드 게시물 row 저장 — INSERT 만 수행.

        S3 업로드는 호출측 (`upload_post`) 이 트랜잭션 밖에서 끝낸 뒤 URL 만 넘긴다.
        본 메서드 동안 DB 커넥션을 점유하는 시간은 INSERT + commit 비용 (~5~20ms) 으로
        한정되어, 동시 업로드 부하 시 풀 점유율이 크게 줄어든다.
        """
        repo = FeedPostRepository(self._session)
        post = FeedPost(
            post_id=post_id,
            user_id=user_id,
            visibility=visibility,
            caption=caption,
            original_url=original_url,
            thumbnail_small_url=small_url,
            thumbnail_medium_url=medium_url,
        )
        saved = await repo.save(post)
        logger.info("피드 게시물 업로드 완료 (user_id={}, post_id={})", user_id, post_id)
        return saved


    # ──────────────────── 조회 ────────────────────

    @transactional
    async def get_my_feed(
        self,
        user_id: str,
        cursor: Optional[str] = None,
    ) -> FeedPostListData:
        """본인 피드 — 모든 visibility 조회.

        next_cursor 는 friend 도메인 컨벤션 그대로 `len(items) == PAGE_SIZE` 면 마지막 post_id.
        """
        repo = FeedPostRepository(self._session)
        posts = await repo.find_by_owner(
            owner_id=user_id,
            visibilities=list(FeedVisibility),  # 본인은 모든 visibility 조회 가능
            cursor=cursor,
        )
        next_cursor = posts[-1].post_id if len(posts) == PAGE_SIZE else None
        return FeedPostListData(
            posts=[self._to_dto(p) for p in posts],
            next_cursor=next_cursor,
        )


    @transactional
    async def get_my_post(self, user_id: str, post_id: str) -> FeedPostData:
        """본인 게시물 단건 조회 — 권한 검증 포함 (다른 유저 게시물 조회는 M3)."""
        post = await self._load_owned_post(user_id, post_id)
        return self._to_dto(post)


    @transactional
    async def get_user_feed(
        self,
        viewer_id: str,
        owner_id: str,
        cursor: Optional[str] = None,
    ) -> FeedPostListData:
        """다른 유저 피드 — 친구/차단/visibility 합성.

        흐름:
            1. viewer 의 owner 피드 접근 권한 + 노출 visibility 부분집합 결정
               (본인/친구/비친구/차단 4 케이스 → `_resolve_viewer_visibilities`)
            2. visibility 부분집합으로 컴파운드 인덱스 IN-scan + 커서 페이지네이션

        viewer == owner 면 본인 피드와 동일한 결과 (모든 visibility) — 프론트가 단일
        엔드포인트로 본인/타인 분기 없이 호출 가능. 차단 관계면 `FeedBlockedError`
        (라우터에서 403). 응답의 `visibility` 는 service 가 이미 PRIVATE 을 필터링했으므로
        타 유저 케이스에서 FRIENDS / PUBLIC 만 노출 — 라우터 docstring 에 명시.
        """
        visibilities = await self._resolve_viewer_visibilities(viewer_id, owner_id)
        repo = FeedPostRepository(self._session)
        posts = await repo.find_by_owner(
            owner_id=owner_id,
            visibilities=visibilities,
            cursor=cursor,
        )
        next_cursor = posts[-1].post_id if len(posts) == PAGE_SIZE else None
        return FeedPostListData(
            posts=[self._to_dto(p) for p in posts],
            next_cursor=next_cursor,
        )


    async def _resolve_viewer_visibilities(
        self,
        viewer_id: str,
        owner_id: str,
    ) -> list[FeedVisibility]:
        """viewer 가 owner 피드에서 볼 수 있는 visibility 부분집합 결정.

        규칙은 `visibility.py::can_view` 가 단일 진입점 — 본 메서드는 enum 에 대해 iterate
        해 부분집합을 만든다. 새 visibility 값이 추가되어도 can_view 만 수정하면 자동 반영.

        본인 fast-path: 차단/친구 조회 없이 모든 visibility 반환 (DB hit 2건 절약).

        raises:
            FeedBlockedError: 양방향 차단 어느 쪽이든 존재 시. 빈 목록 대신 명시적 에러로
                              "친구 추가/피드 보기 진입 자체 차단" UX 를 보장 (plan §5.2).
        """
        if viewer_id == owner_id:
            return list(FeedVisibility)

        block_repo = UserBlockRepository(self._session)
        friend_repo = FriendshipRepository(self._session)

        blocks = await block_repo.find_blocks_between(viewer_id, owner_id)
        if blocks:
            raise FeedBlockedError("차단 관계인 유저의 피드에 접근할 수 없습니다.")

        friendship = await friend_repo.find_between(viewer_id, owner_id)
        is_friend = (
            friendship is not None and friendship.status == FriendshipStatus.ACCEPTED
        )

        return [
            v for v in FeedVisibility
            if can_view(
                viewer_id=viewer_id,
                owner_id=owner_id,
                image_visibility=v,
                is_friend=is_friend,
                is_blocked_either_way=False,  # 위에서 이미 거절됨 — 여기 도달 시 항상 False
            )
        ]


    # ──────────────────── 변경 ────────────────────

    @transactional
    async def update_visibility(
        self,
        user_id: str,
        post_id: str,
        visibility: FeedVisibility,
    ) -> FeedPostData:
        """공개 범위 변경 — 본인만 가능. 즉시 반영 (다음 조회부터 새 visibility 로 필터)."""
        post = await self._load_owned_post(user_id, post_id)
        post.visibility = visibility
        repo = FeedPostRepository(self._session)
        await repo.update(post)
        return self._to_dto(post)


    @transactional
    async def update_caption(
        self,
        user_id: str,
        post_id: str,
        caption: Optional[str],
    ) -> FeedPostData:
        """캡션 변경 — 본인만 가능. null / 빈 문자열 / 공백만 입력 시 캡션 삭제."""
        post = await self._load_owned_post(user_id, post_id)
        post.caption = _normalize_caption(caption)
        repo = FeedPostRepository(self._session)
        await repo.update(post)
        return self._to_dto(post)


    # ──────────────────── 삭제 ────────────────────

    async def delete_post(self, user_id: str, post_id: str) -> None:
        """본인 게시물 삭제 — DB row 먼저, S3 prefix 는 best-effort 정리 (auth/profile 패턴).

        순서 결정:
            DB → S3  : DB 가 비면 더 이상 broken URL 노출 X. S3 실패 = orphan (invisible).
            S3 → DB  : S3 가 먼저 사라진 채 DB 가 살아있으면 broken URL 노출 위험.
        → DB 먼저가 user-facing 면에서 strictly better.

        FK CASCADE + ORM cascade 가 `feed_post_like` / `feed_post_comment` 자동 정리.
        """
        # (트랜잭션) 권한 검증 + DB row 삭제 → 정리할 prefix 반환
        prefix = await self._delete_post_row(user_id, post_id)

        # (트랜잭션 밖) S3 정리 — 실패해도 사용자 작업은 성공 (orphan 만 발생)
        try:
            await self.storage.delete_by_prefix(prefix)
        except Exception as e:
            logger.warning(
                "S3 prefix 삭제 실패 — orphan 객체 잔존 (prefix={}): {}",
                prefix, e,
            )


    @transactional
    async def _delete_post_row(self, user_id: str, post_id: str) -> str:
        """삭제 흐름의 트랜잭션 부분 — 권한 검증 후 PG row 삭제. 정리할 prefix 반환."""
        post = await self._load_owned_post(user_id, post_id)
        prefix = feed_post_prefix(post.user_id, post.post_id)

        repo = FeedPostRepository(self._session)
        await repo.delete(post)
        logger.info("피드 게시물 삭제 완료 (user_id={}, post_id={})", user_id, post_id)
        return prefix


    # ──────────────────── 내부 헬퍼 ────────────────────

    async def _load_owned_post(self, user_id: str, post_id: str) -> FeedPost:
        """post_id 로 게시물 로드 + 본인 소유 검증.

        - 미존재 → FeedNotFoundError (404)
        - 본인 아님 → PermissionError (403, builtin 사용 — tripmate 패턴)
        """
        repo = FeedPostRepository(self._session)
        post = await repo.find_by_post_id(post_id)
        if post is None:
            raise FeedNotFoundError("존재하지 않는 게시물입니다.")
        if post.user_id != user_id:
            raise PermissionError("게시물에 대한 권한이 없습니다.")
        return post


    async def _safe_cleanup(self, prefix: str) -> None:
        """업로드 실패 경로의 best-effort cleanup — 실패해도 swallow + log.

        cleanup 실패 시 orphan S3 객체가 누적되지만, 운영 endpoint (`POST /feed/cleanup`)
        로 사후 정리 가능 (Phase 2). 본 메서드 자체가 raise 하면 원 예외가 가려지므로 swallow.
        """
        try:
            await self.storage.delete_by_prefix(prefix)
        except Exception as e:
            logger.warning(
                "업로드 실패 경로 cleanup 실패 — orphan 객체 잔존 (prefix={}): {}",
                prefix, e,
            )


    @staticmethod
    def _to_dto(post: FeedPost) -> FeedPostData:
        """SQLAlchemy 모델 → DTO. 라우터 직전에서 단일 위치로 변환을 모은다."""
        return FeedPostData(
            post_id=post.post_id,
            user_id=post.user_id,
            visibility=post.visibility,
            caption=post.caption,
            original_url=post.original_url,
            thumbnail_small_url=post.thumbnail_small_url,
            thumbnail_medium_url=post.thumbnail_medium_url,
            created_at=post.created_at,
            updated_at=post.updated_at,
        )
