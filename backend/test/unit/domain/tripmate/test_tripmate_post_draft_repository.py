"""TripmatePostDraftRepository.upsert — 동시 upsert 경합(DuplicateKeyError) 복구 테스트.

user_id unique 인덱스에 draft 가 아직 없을 때 두 PUT(30초 자동저장 + 수동저장)이 경합하면
둘 다 filter 를 놓쳐 insert 시도 → 하나가 unique 위반. 예외를 그대로 던지면 500.
upsert 없이 재조회+갱신으로 복구해 200 을 돌려주는지 회귀 가드
(tripmate_search_history 레포와 동일 패턴).
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pymongo.errors import DuplicateKeyError

from app.domain.tripmate.model.tripmate_post_draft import TripmatePostDraft
from app.domain.tripmate.repository.tripmate_post_draft import TripmatePostDraftRepository


def _draft() -> TripmatePostDraft:
    return TripmatePostDraft(user_id="USER_a", title="여행", image_urls=[])


def _stored_doc() -> dict:
    return {
        "user_id": "USER_a",
        "title": "여행",
        "image_urls": [],
        "updated_at": datetime.now(timezone.utc),
    }


@pytest.mark.unit
class TestUpsertDuplicateKeyRecovery:
    async def test_recovers_when_upsert_races_duplicate_key(self, monkeypatch):
        """첫 upsert 가 DuplicateKeyError → 재조회+갱신으로 복구 (예외 미전파)."""
        stored = _stored_doc()
        collection = MagicMock(name="collection")
        collection.find_one_and_update = AsyncMock(
            side_effect=[DuplicateKeyError("dup"), stored],
        )
        monkeypatch.setattr(
            TripmatePostDraft, "get_motor_collection", lambda *a: collection,
        )

        repo = TripmatePostDraftRepository()
        result = await repo.upsert(_draft())

        assert result.user_id == "USER_a"
        assert collection.find_one_and_update.await_count == 2
        # 복구 재시도는 upsert 없이 호출돼야 (기존 doc 매칭 → 갱신)
        retry_kwargs = collection.find_one_and_update.await_args_list[1].kwargs
        assert "upsert" not in retry_kwargs

    async def test_happy_path_single_call(self, monkeypatch):
        """경합 없으면 upsert 한 번으로 끝 (재시도 없음)."""
        stored = _stored_doc()
        collection = MagicMock(name="collection")
        collection.find_one_and_update = AsyncMock(return_value=stored)
        monkeypatch.setattr(
            TripmatePostDraft, "get_motor_collection", lambda *a: collection,
        )

        repo = TripmatePostDraftRepository()
        result = await repo.upsert(_draft())

        assert result.user_id == "USER_a"
        assert collection.find_one_and_update.await_count == 1
        assert collection.find_one_and_update.await_args.kwargs["upsert"] is True
