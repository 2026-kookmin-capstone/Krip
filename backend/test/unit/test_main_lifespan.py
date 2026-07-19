import asyncio
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from prometheus_client import start_http_server

from app import main as main_module
from app.core.ai.papago_translator.load import PapagoTranslator
from app.core.background_tasks import BackgroundTaskSupervisor


pytestmark = pytest.mark.unit


async def test_stop_metrics_server_releases_thread_and_port():
    server, thread = start_http_server(0, addr="127.0.0.1")
    port = server.server_port

    await main_module._stop_metrics_server(server, thread)

    assert thread.is_alive() is False
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", port))


async def test_instrumentation_failure_resets_monitor_and_disposes_engine(monkeypatch):
    class MetricsServer:
        shutdown = MagicMock()
        server_close = MagicMock()

    class MetricsThread:
        join = MagicMock()

    engine = MagicMock()
    engine.dispose = AsyncMock()
    lock_engine = MagicMock()
    lock_engine.dispose = AsyncMock()
    stop_monitor = AsyncMock()
    app = SimpleNamespace(
        container=SimpleNamespace(
            engine=lambda: engine,
            image_reference_lock_engine=lambda: lock_engine,
        ),
    )

    monkeypatch.setattr(main_module, "setup_logging", lambda: None)
    monkeypatch.setattr(
        main_module,
        "start_http_server",
        lambda _port: (MetricsServer(), MetricsThread()),
    )
    monkeypatch.setattr(main_module, "prime_worker_gauges", lambda: None)
    monkeypatch.setattr(
        main_module,
        "attach_db_instrumentation",
        MagicMock(side_effect=RuntimeError("instrumentation failed")),
    )
    monkeypatch.setattr(main_module, "stop_event_loop_monitor", stop_monitor)

    lifespan = main_module.app.router.lifespan_context
    with pytest.raises(RuntimeError, match="instrumentation failed"):
        async with lifespan(app):
            pytest.fail("startup failure must prevent yield")

    stop_monitor.assert_awaited_once()
    engine.dispose.assert_awaited_once()
    lock_engine.dispose.assert_awaited_once()


async def test_papago_close_releases_partially_loaded_model():
    translator = PapagoTranslator()
    model = SimpleNamespace(close_client=AsyncMock())
    setattr(translator, "_model", model)
    translator._initialized = False

    await translator.close()

    model.close_client.assert_awaited_once()


@pytest.mark.parametrize(
    ("failure", "expected_cleanup"),
    [
        (
            "mongodb",
            ["stop_mongodb", "stop_event_monitor", "dispose_lock_engine", "dispose_engine",
             "stop_metrics_server", "close_metrics_server", "join_metrics_thread"],
        ),
        (
            "dedupe",
            ["stop_redis", "stop_mongodb", "stop_event_monitor", "dispose_lock_engine",
             "dispose_engine",
             "stop_metrics_server", "close_metrics_server", "join_metrics_thread"],
        ),
        (
            "fcm",
            ["stop_fcm", "stop_redis", "stop_mongodb", "stop_event_monitor",
             "dispose_lock_engine", "dispose_engine", "stop_metrics_server", "close_metrics_server",
             "join_metrics_thread"],
        ),
        (
            "node",
            ["stop_registry", "stop_dispatcher", "stop_reconcile", "stop_fcm",
             "stop_redis", "stop_mongodb", "stop_event_monitor", "dispose_lock_engine", "dispose_engine",
             "stop_metrics_server", "close_metrics_server", "join_metrics_thread"],
        ),
        (
            "papago",
            ["close_papago", "stop_purge", "stop_registry", "stop_dispatcher",
             "stop_reconcile", "stop_fcm", "stop_redis", "stop_mongodb",
             "stop_event_monitor", "dispose_lock_engine", "dispose_engine", "stop_metrics_server",
             "close_metrics_server", "join_metrics_thread"],
        ),
    ],
)
async def test_startup_failure_cleans_started_resources_in_reverse_order(
    monkeypatch, failure, expected_cleanup,
):
    events: list[str] = []

    class MetricsServer:
        def shutdown(self):
            events.append("stop_metrics_server")

        def server_close(self):
            events.append("close_metrics_server")

    class MetricsThread:
        def join(self):
            events.append("join_metrics_thread")

    async def record_async(name):
        events.append(name)

    def record_sync(name):
        events.append(name)

    async def start_async(name):
        events.append(f"start_{name}")
        if failure == name:
            raise RuntimeError(f"{name} startup failed")

    def start_sync(name):
        events.append(f"start_{name}")
        if failure == name:
            raise RuntimeError(f"{name} startup failed")

    async def dispose_engine():
        await record_async("dispose_engine")

    async def dispose_lock_engine():
        await record_async("dispose_lock_engine")

    engine = MagicMock()
    engine.dispose = AsyncMock(side_effect=dispose_engine)
    lock_engine = MagicMock()
    lock_engine.dispose = AsyncMock(side_effect=dispose_lock_engine)
    container = SimpleNamespace(
        engine=lambda: engine,
        image_reference_lock_engine=lambda: lock_engine,
        session_factory=lambda: object(),
        fanout_service=lambda: object(),
    )
    app = SimpleNamespace(container=container)

    monkeypatch.setattr(main_module, "setup_logging", lambda: None)
    monkeypatch.setattr(
        main_module,
        "start_http_server",
        lambda _port: (MetricsServer(), MetricsThread()),
    )
    monkeypatch.setattr(main_module, "prime_worker_gauges", lambda: None)
    monkeypatch.setattr(main_module, "attach_db_instrumentation", lambda _engine: None)
    monkeypatch.setattr(
        main_module, "start_event_loop_monitor", lambda: start_sync("event_monitor")
    )
    monkeypatch.setattr(
        main_module,
        "stop_event_loop_monitor",
        lambda: record_async("stop_event_monitor"),
    )
    monkeypatch.setattr(main_module, "init_mongodb", lambda: start_async("mongodb"))
    monkeypatch.setattr(main_module, "close_mongodb", lambda: record_async("stop_mongodb"))
    monkeypatch.setattr(main_module, "get_redis_client", lambda: start_async("redis"))
    monkeypatch.setattr(main_module, "get_redis_dedupe_client", lambda: start_async("dedupe"))
    monkeypatch.setattr(main_module, "close_redis", lambda: record_async("stop_redis"))
    monkeypatch.setattr(main_module.lua_scripts, "load", lambda _redis: None)
    monkeypatch.setattr(main_module, "init_fcm", lambda: start_sync("fcm"))
    monkeypatch.setattr(main_module, "close_fcm", lambda: record_sync("stop_fcm"))
    monkeypatch.setattr(
        main_module,
        "start_reconcile_scheduler",
        lambda _factory: start_sync("reconcile"),
    )
    monkeypatch.setattr(
        main_module,
        "stop_reconcile_scheduler",
        lambda: record_async("stop_reconcile"),
    )
    monkeypatch.setattr(
        main_module,
        "start_fanout_dispatcher",
        lambda _fanout: start_async("dispatcher"),
    )
    monkeypatch.setattr(
        main_module,
        "stop_fanout_dispatcher",
        lambda: record_async("stop_dispatcher"),
    )
    monkeypatch.setattr(
        main_module, "start_node_registry", lambda: start_async("node")
    )
    monkeypatch.setattr(
        main_module, "stop_node_registry", lambda: record_async("stop_registry")
    )
    monkeypatch.setattr(
        main_module,
        "start_withdraw_purge_scheduler",
        lambda _factory: start_sync("purge"),
    )
    monkeypatch.setattr(
        main_module,
        "stop_withdraw_purge_scheduler",
        lambda: record_async("stop_purge"),
    )

    class Menu:
        def load(self):
            start_sync("menu")

    class Papago:
        def load(self):
            start_sync("papago")

        async def close(self):
            await record_async("close_papago")

    class Tour:
        async def load(self):
            pytest.fail("TourPlanner must not load after Papago startup failure")

    monkeypatch.setattr(main_module, "MenuOcr", Menu)
    monkeypatch.setattr(main_module, "PapagoTranslator", Papago)
    monkeypatch.setattr(main_module, "TourPlanner", Tour)

    lifespan = main_module.app.router.lifespan_context
    with pytest.raises(RuntimeError, match=f"{failure} startup failed"):
        async with lifespan(app):
            pytest.fail("startup failure must prevent yield")

    cleanup_events = [event for event in events if event.startswith(("stop_", "close_", "join_", "dispose_"))]
    assert cleanup_events == expected_cleanup


async def test_lifespan_stops_background_tasks_before_shared_resources(monkeypatch):
    events: list[str] = []

    class MetricsServer:
        shutdown = MagicMock()
        server_close = MagicMock()

    class MetricsThread:
        join = MagicMock()

    async def noop_async(*_args, **_kwargs):
        return None

    def noop(*_args, **_kwargs):
        return None

    engine = MagicMock()
    engine.dispose = AsyncMock(side_effect=lambda: events.append("dispose_engine"))
    lock_engine = MagicMock()
    lock_engine.dispose = AsyncMock(side_effect=lambda: events.append("dispose_lock_engine"))
    app = SimpleNamespace(container=SimpleNamespace(
        engine=lambda: engine,
        image_reference_lock_engine=lambda: lock_engine,
        session_factory=lambda: object(),
        fanout_service=lambda: object(),
    ))
    supervisor = BackgroundTaskSupervisor(shutdown_grace_sec=0)

    monkeypatch.setattr(main_module, "background_tasks", supervisor, raising=False)
    monkeypatch.setattr(main_module, "setup_logging", noop)
    monkeypatch.setattr(main_module, "start_http_server", lambda _port: (MetricsServer(), MetricsThread()))
    monkeypatch.setattr(main_module, "prime_worker_gauges", noop)
    monkeypatch.setattr(main_module, "attach_db_instrumentation", noop)
    monkeypatch.setattr(main_module, "start_event_loop_monitor", noop)
    monkeypatch.setattr(main_module, "stop_event_loop_monitor", noop_async)
    monkeypatch.setattr(main_module, "init_mongodb", noop_async)
    monkeypatch.setattr(main_module, "close_mongodb", lambda: events.append("close_mongodb") or noop_async())
    monkeypatch.setattr(main_module, "get_redis_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(main_module, "get_redis_dedupe_client", AsyncMock(return_value=object()))
    monkeypatch.setattr(main_module, "close_redis", lambda: events.append("close_redis") or noop_async())
    monkeypatch.setattr(main_module.lua_scripts, "load", noop)
    monkeypatch.setattr(main_module, "init_fcm", noop)
    monkeypatch.setattr(main_module, "close_fcm", lambda: events.append("close_fcm"))
    monkeypatch.setattr(main_module, "start_reconcile_scheduler", noop)
    monkeypatch.setattr(main_module, "stop_reconcile_scheduler", noop_async)
    monkeypatch.setattr(main_module, "start_fanout_dispatcher", noop_async)
    monkeypatch.setattr(main_module, "stop_fanout_dispatcher", noop_async)
    monkeypatch.setattr(main_module, "start_node_registry", noop_async)
    monkeypatch.setattr(main_module, "stop_node_registry", noop_async)
    monkeypatch.setattr(main_module, "start_withdraw_purge_scheduler", noop)
    monkeypatch.setattr(main_module, "stop_withdraw_purge_scheduler", noop_async)
    monkeypatch.setattr(main_module, "MenuOcr", lambda: SimpleNamespace(load=noop))
    monkeypatch.setattr(
        main_module, "PapagoTranslator",
        lambda: SimpleNamespace(load=noop, close=noop_async),
    )
    monkeypatch.setattr(main_module, "TourPlanner", lambda: SimpleNamespace(load=noop_async))

    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def background_work():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            events.append("cleanup_background")
            cleaned.set()

    async with main_module.app.router.lifespan_context(app):
        task = supervisor.spawn(background_work(), name="lifespan-e2e")
        await started.wait()
        assert task is not None and not task.done()

    assert cleaned.is_set()
    assert task.done()
    assert events.index("cleanup_background") < events.index("close_fcm")
    assert events.index("cleanup_background") < events.index("close_redis")
    assert events.index("cleanup_background") < events.index("close_mongodb")
    assert events.index("cleanup_background") < events.index("dispose_engine")
