import asyncio
import io
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.database.session import UnitOfWork
from app.domain.auth.model.user_detail_inform import UserDetailInform
from app.domain.auth.service.profile import ProfileService


pytestmark = pytest.mark.integration
_NEW_URL = "https://storage.example.com/profile/new.jpg"
_OLD_URL = "https://storage.example.com/profile/old.jpg"


class _CommitAppliedThenCancelledFactory:
    def __init__(self, session_factory):
        self._session_factory = session_factory
        self._raise_after_next_commit = True

    def __call__(self):
        return _CommitAppliedThenCancelledSession(self._session_factory(), self)


class _CommitAppliedThenCancelledSession:
    def __init__(self, session, owner):
        self._session = session
        self._owner = owner

    def __getattr__(self, name):
        return getattr(self._session, name)

    async def commit(self):
        await self._session.commit()
        if self._owner._raise_after_next_commit:
            self._owner._raise_after_next_commit = False
            raise asyncio.CancelledError


async def _current_url(session_factory, user_id: str) -> str | None:
    async with session_factory() as session:
        return await session.scalar(
            select(UserDetailInform.profile_image_url).where(UserDetailInform.user_id == user_id),
        )


@pytest.mark.parametrize("operation", ["add", "update"])
async def test_commit_response_loss_preserves_referenced_public_object(
    operation, session_factory, seed_users,
):
    [user_id] = await seed_users(1)
    if operation == "update":
        async with session_factory() as session:
            detail = await session.get(UserDetailInform, user_id)
            detail.profile_image_url = _OLD_URL
            await session.commit()

    service = ProfileService(
        UnitOfWork(session=cast(Any, _CommitAppliedThenCancelledFactory(session_factory))),
    )
    service.storage = AsyncMock()
    service.storage.upload_perm.return_value = _NEW_URL

    method = service.add_profile_image if operation == "add" else service.update_profile_image
    with pytest.raises(asyncio.CancelledError):
        await method(
            user_id=user_id,
            file=io.BytesIO(b"image"),
            file_name="profile.jpg",
            content_type="image/jpeg",
        )

    assert await _current_url(session_factory, user_id) == _NEW_URL
    service.storage.delete.assert_not_awaited()
