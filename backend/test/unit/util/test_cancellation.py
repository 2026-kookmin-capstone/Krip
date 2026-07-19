"""cancellation drain 헬퍼 — thread drain과 contextvars 전파 검증."""
import asyncio
import contextvars

import pytest

from app.util.cancellation import drain_thread_on_cancellation


pytestmark = pytest.mark.unit

_request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "test_request_id", default="",
)


async def test_thread_sees_caller_contextvars():
    """`asyncio.to_thread`와 동일하게 contextvars가 thread로 복사돼
    thread 내 로그가 request_id 상관관계를 유지한다."""
    _request_id_var.set("REQ_1")

    result, cancelled = await drain_thread_on_cancellation(_request_id_var.get)

    assert result == "REQ_1"
    assert cancelled is False


async def test_cancellation_waits_for_thread_and_reports_flag():
    """취소돼도 thread 종료까지 대기한 뒤 결과와 cancelled=True를 함께 반환한다."""
    thread_started = asyncio.Event()
    release_thread = asyncio.Event()
    loop = asyncio.get_running_loop()

    def blocking_work() -> str:
        loop.call_soon_threadsafe(thread_started.set)
        asyncio.run_coroutine_threadsafe(release_thread.wait(), loop).result(timeout=5)
        return "done"

    async def run() -> tuple[str, bool]:
        return await drain_thread_on_cancellation(blocking_work)

    task = asyncio.create_task(run())
    await asyncio.wait_for(thread_started.wait(), timeout=5)
    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()  # 취소 후에도 thread가 끝날 때까지 대기

    release_thread.set()
    result, cancelled = await asyncio.wait_for(task, timeout=5)
    assert result == "done"
    assert cancelled is True
