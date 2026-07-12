"""InboxItem 컬렉션 e2e 통합 테스트 (실 Mongo).

unit 테스트가 mock 으로 검증할 수 없는 영역을 cover:
    - `uq_inbox_dedup` partial unique 인덱스가 실 Mongo 에 적용되어 동작
    - `display=true` 조건 partial filter 가 정확히 작동 (X 후 새 항목 가능)
    - atomic update (`hide` / `mark_read_by_ids`) 가 race-free
    - keyset cursor `(created_at, _id)` tiebreak 이 같은 ms 항목을 페이지 경계에서 누락 안 함
    - cascade `delete_by_user` 의 `$or` 매칭

검증 매트릭스:

    | 시나리오                                | 기대                                    |
    |---|---|
    | insert + list (display=true)            | 응답에 보임                              |
    | 같은 (recipient, actor, type, target)   | DuplicateKeyError (partial unique 충돌) |
    | 첫 항목 hide → 같은 키 새 insert        | 성공 (display=false 는 인덱스 밖)       |
    | mark_as_read=True 후 read_at 채워짐     | DB read_at != null (노출된 항목만)      |
    | 응답 dto.is_read 는 mark 전 상태        | False (인스타 패턴)                      |
    | hide 후 list 에서 제외                  | response 에 안 나옴                     |
    | count_unread (display=true & null)      | 정확한 카운트 (cap 999)                  |
    | cascade_user_withdrawn (recipient/actor)| 양쪽 매칭 모두 삭제                      |
"""
from datetime import datetime, timezone

import pytest
from pymongo.errors import DuplicateKeyError

from app.domain.notification.model.inbox import (
    InboxItem,
    InboxItemType,
    TargetType,
)
from app.domain.notification.repository.inbox import InboxRepository
from app.domain.notification.service.exception import InboxItemNotFoundError


pytestmark = pytest.mark.integration


def _make_inbox_item(
    *,
    recipient_id: str = "USER_recipient",
    actor_id: str = "USER_actor",
    type: InboxItemType = InboxItemType.FEED_LIKE,
    target_id: str = "FDP_x",
    comment_id: str | None = None,
    actor_name: str = "actorName",
) -> InboxItem:
    """test 용 InboxItem 인스턴스 — 실 mongo 에 insert 가능한 minimal 형태."""
    return InboxItem(
        recipient_id=recipient_id,
        actor_id=actor_id,
        type=type,
        target_type=TargetType.FEED_POST if type != InboxItemType.TRIPMATE_LIKE else TargetType.TRIPMATE_POST,
        target_id=target_id,
        comment_id=comment_id,
        actor_name=actor_name,
    )


class TestPartialUniqueIndex:
    """`uq_inbox_dedup` 인덱스가 실 mongo 에 적용되어 의도대로 동작하는지.

    좋아요 취소→재좋아요 시 항목 폭증 방지의 핵심 가드. unit 은 mock 이라 인덱스 자체를
    검증 못 함 — 통합으로만 보장 가능.
    """

    async def test_duplicate_active_item_raises(self, mongo_db):
        """display=true 인 같은 (recipient, actor, type, target, null comment) 조합 → 충돌."""
        repo = InboxRepository()

        await repo.insert(_make_inbox_item())

        with pytest.raises(DuplicateKeyError):
            await repo.insert(_make_inbox_item())

    async def test_hide_then_reinsert_succeeds(self, mongo_db, inbox_service):
        """X 로 숨긴(display=false) 항목은 partial filter 밖 → 같은 키 새 insert 가능.

        Q1 결정: "X 후 같은 사람이 다시 좋아요 → 새 항목 OK". 실 인덱스로 보장.
        """
        repo = InboxRepository()
        first = _make_inbox_item()
        await repo.insert(first)

        # X 버튼 — display=false
        await inbox_service.hide_item(
            recipient_id="USER_recipient",
            inbox_item_id=str(first.id),
        )

        # 같은 키 새 항목 — partial filter 에서 첫 번째 빠짐 → 성공
        second = _make_inbox_item()
        await repo.insert(second)

        # 둘 다 DB 에 존재 (display=false + display=true)
        coll = InboxItem.get_motor_collection()
        assert await coll.count_documents({"recipient_id": "USER_recipient"}) == 2

    async def test_different_comment_ids_dont_conflict(self, mongo_db):
        """COMMENT 항목은 comment_id 가 매번 달라 자연 unique."""
        repo = InboxRepository()

        await repo.insert(_make_inbox_item(
            type=InboxItemType.FEED_COMMENT, comment_id="CMT_1",
        ))
        await repo.insert(_make_inbox_item(
            type=InboxItemType.FEED_COMMENT, comment_id="CMT_2",
        ))


class TestListInboxFlow:
    """인박스 e2e — 페이지네이션 + 자동 mark_as_read 의 atomic update."""

    async def test_list_returns_inserted_in_reverse_chronological(
        self, mongo_db, inbox_service,
    ):
        """insert 순서대로 → list 는 최신순 (reverse)."""
        repo = InboxRepository()
        for i in range(3):
            await repo.insert(_make_inbox_item(
                target_id=f"FDP_{i}", actor_id=f"USER_a_{i}",
            ))

        result = await inbox_service.list_items(
            recipient_id="USER_recipient",
        )

        assert len(result.items) == 3
        assert result.items[0].target_id == "FDP_2"
        assert result.items[2].target_id == "FDP_0"

    async def test_mark_as_read_true_updates_db_atomically(
        self, mongo_db, inbox_service,
    ):
        """`mark_as_read=True` → DB 의 read_at 이 모두 채워짐. atomic update_many."""
        repo = InboxRepository()
        await repo.insert(_make_inbox_item(target_id="FDP_1"))
        await repo.insert(_make_inbox_item(target_id="FDP_2", actor_id="USER_b"))

        await inbox_service.list_items(
            recipient_id="USER_recipient", mark_as_read=True,
        )

        coll = InboxItem.get_motor_collection()
        unread = await coll.count_documents(
            {"recipient_id": "USER_recipient", "read_at": None},
        )
        assert unread == 0

    async def test_response_is_read_reflects_pre_mark_state(
        self, mongo_db, inbox_service,
    ):
        """응답 dto 의 is_read 는 mark 전 상태 (False) — 인스타 강조 패턴.

        DB 는 mark 후 상태. 응답엔 read 전 상태. 다음 진입 시 강조 사라짐.
        """
        repo = InboxRepository()
        await repo.insert(_make_inbox_item())

        result = await inbox_service.list_items(
            recipient_id="USER_recipient", mark_as_read=True,
        )

        # 응답 — mark 전 상태
        assert result.items[0].is_read is False
        # DB — mark 후 상태
        coll = InboxItem.get_motor_collection()
        unread = await coll.count_documents(
            {"recipient_id": "USER_recipient", "read_at": None},
        )
        assert unread == 0

    async def test_mark_as_read_false_keeps_unread(
        self, mongo_db, inbox_service,
    ):
        """더 보기(`cursor` 있음) — read 처리 호출 안 됨. read_at 유지."""
        repo = InboxRepository()
        await repo.insert(_make_inbox_item())

        await inbox_service.list_items(
            recipient_id="USER_recipient", mark_as_read=False,
        )

        coll = InboxItem.get_motor_collection()
        unread = await coll.count_documents(
            {"recipient_id": "USER_recipient", "read_at": None},
        )
        assert unread == 1


class TestKeysetCursorTiebreak:
    """`(created_at, _id)` 복합 keyset 이 같은 ms 항목을 페이지 경계에서 누락 안 하는지.

    BSON datetime 은 ms 정밀도라, burst fan-out 이 같은 ms 에 몰리고 그 경계가 페이지에
    걸치면 `created_at < cursor` 단일 조건은 등가 timestamp 항목을 영구히 건너뛴다.
    repo 의 keyset predicate 로 tiebreak 되는지 실 mongo 로 검증.
    """

    async def test_same_ms_items_not_dropped_across_page_boundary(self, mongo_db):
        repo = InboxRepository()
        ts = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)  # 마이크로초 0 → 동일 ms

        inserted = []
        for i in range(3):
            item = _make_inbox_item(actor_id=f"USER_a_{i}", target_id=f"FDP_{i}")
            item.created_at = ts  # 3건 모두 같은 created_at
            await repo.insert(item)
            inserted.append(item)

        # limit=2 → 첫 페이지 (limit+1=3 fetch 후 2건 노출), 나머지 1건은 keyset 으로 이어받음
        page1_raw = await repo.find_by_recipient("USER_recipient", cursor=None, limit=2)
        page1 = page1_raw[:2]
        last = page1[-1]

        page2 = await repo.find_by_recipient(
            "USER_recipient", cursor=(last.created_at, last.id), limit=2,
        )

        seen = {str(i.id) for i in page1} | {str(i.id) for i in page2}
        # 같은 ms 3건이 하나도 누락되지 않고 두 페이지에 온전히 등장
        assert {str(i.id) for i in inserted} <= seen
        # 페이지 간 중복도 없음
        assert not ({str(i.id) for i in page1} & {str(i.id) for i in page2})


class TestHideAtomic:
    """`hide` 가 atomic update 로 권한 검증 + 토글."""

    async def test_hide_excludes_from_list(self, mongo_db, inbox_service):
        repo = InboxRepository()
        item = _make_inbox_item()
        await repo.insert(item)

        await inbox_service.hide_item(
            recipient_id="USER_recipient",
            inbox_item_id=str(item.id),
        )

        result = await inbox_service.list_items(
            recipient_id="USER_recipient",
        )
        assert result.items == []

    async def test_hide_other_user_raises_not_found(
        self, mongo_db, inbox_service,
    ):
        """타인 항목 hide 시도 → atomic query 매칭 실패 → NotFound 일원화."""
        repo = InboxRepository()
        item = _make_inbox_item(recipient_id="USER_other")
        await repo.insert(item)

        with pytest.raises(InboxItemNotFoundError):
            await inbox_service.hide_item(
                recipient_id="USER_recipient",
                inbox_item_id=str(item.id),
            )

    async def test_hide_invalid_objectid_raises_not_found(
        self, mongo_db, inbox_service,
    ):
        with pytest.raises(InboxItemNotFoundError):
            await inbox_service.hide_item(
                recipient_id="USER_recipient",
                inbox_item_id="not-an-objectid",
            )


class TestCountUnread:
    async def test_counts_only_unread_displayed(self, mongo_db, inbox_service):
        repo = InboxRepository()
        # 3건 insert — 모두 미읽음 / display=true
        for i in range(3):
            await repo.insert(_make_inbox_item(
                target_id=f"FDP_{i}", actor_id=f"USER_a_{i}",
            ))

        count = await inbox_service.count_unread(recipient_id="USER_recipient")

        assert count == 3

    async def test_excludes_hidden_items(
        self, mongo_db, inbox_service,
    ):
        """display=false (X 누름) 는 미읽음 카운트에서 제외."""
        repo = InboxRepository()
        n1 = _make_inbox_item(target_id="FDP_1")
        n2 = _make_inbox_item(target_id="FDP_2", actor_id="USER_b")
        await repo.insert(n1)
        await repo.insert(n2)

        await inbox_service.hide_item(
            recipient_id="USER_recipient", inbox_item_id=str(n1.id),
        )

        count = await inbox_service.count_unread(recipient_id="USER_recipient")

        assert count == 1


class TestCascadeUserWithdrawn:
    """탈퇴 cascade — recipient 또는 actor 매칭 항목 모두 삭제."""

    async def test_deletes_recipient_and_actor_matching(
        self, mongo_db, inbox_service,
    ):
        repo = InboxRepository()
        # USER_x 가 받은 항목
        await repo.insert(_make_inbox_item(
            recipient_id="USER_x", actor_id="USER_a",
        ))
        # USER_x 가 보낸 항목 (다른 사람이 받음)
        await repo.insert(_make_inbox_item(
            recipient_id="USER_b", actor_id="USER_x",
        ))
        # 무관한 항목 (보존되어야)
        await repo.insert(_make_inbox_item(
            recipient_id="USER_c", actor_id="USER_d",
        ))

        deleted = await inbox_service.cascade_user_withdrawn(user_id="USER_x")

        assert deleted == 2
        coll = InboxItem.get_motor_collection()
        assert await coll.count_documents({}) == 1
        # 무관한 항목은 보존
        remaining = await coll.find_one({})
        assert remaining["recipient_id"] == "USER_c"
