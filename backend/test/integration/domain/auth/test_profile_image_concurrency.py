import asyncio
import io
from collections.abc import Awaitable, Callable
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from app.database.session import UnitOfWork
from app.domain.auth.model.user_detail_inform import UserDetailInform
from app.domain.auth.repository.user_detail_inform import UserDetailInformRepository
from app.domain.auth.service.exception import (
    ProfileImageAlreadyExistsError,
    ProfileImageNotFoundError,
)
from app.domain.auth.service.profile import ProfileService


pytestmark = pytest.mark.integration
_OLD_URL = "https://storage.example.com/profile/old.jpg"


async def _services_with_storage(session_factory, objects: set[str]):
    storage = AsyncMock()
    next_upload = 0

    async def upload(*_args, **_kwargs):
        nonlocal next_upload
        next_upload += 1
        url = f"https://storage.example.com/profile/new-{next_upload}.jpg"
        objects.add(url)
        return url

    async def delete(url: str):
        objects.discard(url)

    storage.upload_perm.side_effect = upload
    storage.delete.side_effect = delete
    services = [
        ProfileService(UnitOfWork(session=session_factory)),
        ProfileService(UnitOfWork(session=session_factory)),
    ]
    for service in services:
        service.storage = storage
    return services


def _pause_first_update(monkeypatch):
    original = UserDetailInformRepository.update
    entered = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def update(repo, detail):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        return await original(repo, detail)

    monkeypatch.setattr(UserDetailInformRepository, "update", update)
    return entered, release


async def _assert_row_is_locked(session_factory, user_id: str) -> None:
    async with session_factory() as session:
        stmt = (
            select(UserDetailInform)
            .where(UserDetailInform.user_id == user_id)
            .with_for_update(nowait=True)
        )
        with pytest.raises(DBAPIError) as error:
            await asyncio.wait_for(session.execute(stmt), timeout=2)
        assert getattr(error.value.orig, "sqlstate", None) == "55P03"


async def _run_serialized(
    first: Callable[[], Awaitable[Any]],
    second: Callable[[], Awaitable[Any]],
    *,
    entered: asyncio.Event,
    release: asyncio.Event,
    session_factory,
    user_id: str,
) -> list[Any]:
    tasks = [asyncio.ensure_future(first())]
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        await _assert_row_is_locked(session_factory, user_id)
        tasks.append(asyncio.ensure_future(second()))
        release.set()
        _, pending = await asyncio.wait(tasks, timeout=2)
        if pending:
            raise TimeoutError("profile image operations did not finish")
        results: list[Any] = []
        for task in tasks:
            try:
                results.append(task.result())
            except BaseException as error:
                results.append(error)
        return results
    finally:
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        _, pending = await asyncio.wait(tasks, timeout=2)
        if pending:
            raise AssertionError("profile image test tasks did not stop")
        for task in tasks:
            if task.cancelled():
                continue
            task.exception()


async def test_concurrent_add_compensates_loser_upload(
    session_factory, seed_users, monkeypatch,
):
    [user_id] = await seed_users(1)
    objects: set[str] = set()
    services = await _services_with_storage(session_factory, objects)
    entered, release = _pause_first_update(monkeypatch)

    def add(service):
        return service.add_profile_image(
            user_id=user_id,
            file=io.BytesIO(b"image"),
            file_name="profile.jpg",
            content_type="image/jpeg",
        )

    results = await _run_serialized(
        lambda: add(services[0]), lambda: add(services[1]),
        entered=entered, release=release,
        session_factory=session_factory, user_id=user_id,
    )

    async with session_factory() as session:
        current_url = (await session.get(UserDetailInform, user_id)).profile_image_url

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, ProfileImageAlreadyExistsError) for result in results) == 1
    assert objects == {current_url}


async def test_concurrent_update_removes_superseded_upload(
    session_factory, seed_users, monkeypatch,
):
    [user_id] = await seed_users(1)
    async with session_factory() as session:
        detail = await session.get(UserDetailInform, user_id)
        detail.profile_image_url = _OLD_URL
        await session.commit()

    objects = {_OLD_URL}
    services = await _services_with_storage(session_factory, objects)
    entered, release = _pause_first_update(monkeypatch)

    def update(service):
        return service.update_profile_image(
            user_id=user_id,
            file=io.BytesIO(b"image"),
            file_name="profile.jpg",
            content_type="image/jpeg",
        )

    results = await _run_serialized(
        lambda: update(services[0]), lambda: update(services[1]),
        entered=entered, release=release,
        session_factory=session_factory, user_id=user_id,
    )

    async with session_factory() as session:
        current_url = (await session.get(UserDetailInform, user_id)).profile_image_url

    assert all(not isinstance(result, BaseException) for result in results)
    assert objects == {current_url}


async def test_concurrent_update_then_delete_leaves_no_public_object(
    session_factory, seed_users, monkeypatch,
):
    [user_id] = await seed_users(1)
    async with session_factory() as session:
        detail = await session.get(UserDetailInform, user_id)
        detail.profile_image_url = _OLD_URL
        await session.commit()

    objects = {_OLD_URL}
    services = await _services_with_storage(session_factory, objects)
    entered, release = _pause_first_update(monkeypatch)

    async def update():
        return await services[0].update_profile_image(
            user_id=user_id,
            file=io.BytesIO(b"image"),
            file_name="profile.jpg",
            content_type="image/jpeg",
        )

    results = await _run_serialized(
        update, lambda: services[1].delete_profile_image(user_id),
        entered=entered, release=release,
        session_factory=session_factory, user_id=user_id,
    )

    async with session_factory() as session:
        current_url = (await session.get(UserDetailInform, user_id)).profile_image_url

    assert all(not isinstance(result, BaseException) for result in results)
    assert current_url is None
    assert objects == set()


async def test_concurrent_delete_then_update_compensates_candidate(
    session_factory, seed_users, monkeypatch,
):
    [user_id] = await seed_users(1)
    async with session_factory() as session:
        detail = await session.get(UserDetailInform, user_id)
        detail.profile_image_url = _OLD_URL
        await session.commit()

    objects = {_OLD_URL}
    services = await _services_with_storage(session_factory, objects)
    entered, release = _pause_first_update(monkeypatch)

    def update():
        return services[1].update_profile_image(
            user_id=user_id,
            file=io.BytesIO(b"image"),
            file_name="profile.jpg",
            content_type="image/jpeg",
        )

    results = await _run_serialized(
        lambda: services[0].delete_profile_image(user_id), update,
        entered=entered, release=release,
        session_factory=session_factory, user_id=user_id,
    )

    async with session_factory() as session:
        current_url = (await session.get(UserDetailInform, user_id)).profile_image_url

    assert sum(not isinstance(result, BaseException) for result in results) == 1
    assert sum(isinstance(result, ProfileImageNotFoundError) for result in results) == 1
    assert current_url is None
    assert objects == set()
