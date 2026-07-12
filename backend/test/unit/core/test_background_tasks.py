import asyncio

import pytest

from app.core.background_tasks import BackgroundTaskSupervisor


pytestmark = pytest.mark.unit


async def test_stop_drains_task_that_finishes_within_grace():
    supervisor = BackgroundTaskSupervisor(shutdown_grace_sec=0.1)
    supervisor.start()
    release = asyncio.Event()
    finished = asyncio.Event()

    async def work():
        await release.wait()
        finished.set()

    supervisor.spawn(work(), name="drain-me")
    stop_task = asyncio.create_task(supervisor.stop())
    await asyncio.sleep(0)

    assert not stop_task.done()
    release.set()
    await stop_task

    assert finished.is_set()
    assert not supervisor.tasks


async def test_stop_cancels_after_grace_and_waits_for_cleanup():
    supervisor = BackgroundTaskSupervisor(shutdown_grace_sec=0)
    supervisor.start()
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def work():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    task = supervisor.spawn(work(), name="cancel-me")
    await started.wait()
    await supervisor.stop()

    assert task is not None
    assert task.done()
    assert task.cancelled()
    assert cleaned.is_set()
    assert not supervisor.tasks


async def test_cancelled_stop_still_cancels_and_drains_tasks():
    supervisor = BackgroundTaskSupervisor(shutdown_grace_sec=10)
    supervisor.start()
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def work():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    task = supervisor.spawn(work(), name="shutdown-cancel")
    await started.wait()
    stop_task = asyncio.create_task(supervisor.stop())
    await asyncio.sleep(0)
    stop_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await stop_task

    assert task is not None
    assert task.done()
    assert cleaned.is_set()
    assert not supervisor.tasks


async def test_spawn_after_stop_closes_coroutine_without_running_it():
    supervisor = BackgroundTaskSupervisor(shutdown_grace_sec=0)
    supervisor.start()
    await supervisor.stop()
    ran = False

    async def work():
        nonlocal ran
        ran = True

    coroutine = work()
    task = supervisor.spawn(coroutine, name="too-late")

    assert task is None
    assert coroutine.cr_frame is None
    assert ran is False
