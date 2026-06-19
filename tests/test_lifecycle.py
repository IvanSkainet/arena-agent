"""Lifecycle extraction tests."""
import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.app_keys import APP_CFG, APP_LOG_CLEANUP, APP_TASK_RUNNER  # noqa: E402
from arena.lifecycle import LifecycleContext, make_lifecycle  # noqa: E402


def _ctx(events, executor=None, slow_executor=None):
    executor = executor or ThreadPoolExecutor(max_workers=1)
    slow_executor = slow_executor or ThreadPoolExecutor(max_workers=1)

    async def dummy_loop(app):
        try:
            while True:
                await asyncio.sleep(10)
        except asyncio.CancelledError:
            raise

    async def stop_grpc():
        events.append("stop_grpc")

    async def stop_cluster():
        events.append("stop_cluster")

    return LifecycleContext(
        executor=executor,
        slow_executor=slow_executor,
        init_memory_db=lambda: events.append("init_memory"),
        task_runner_loop=dummy_loop,
        log_cleanup_loop=dummy_loop,
        start_watchdog=lambda: events.append("start_watchdog"),
        stop_watchdog=lambda: events.append("stop_watchdog"),
        stop_cdp_watcher=lambda: events.append("stop_cdp"),
        cdp_state={"manager": None},
        stop_grpc_server=stop_grpc,
        stop_cluster_heartbeat=stop_cluster,
        get_shutdown_event=lambda: None,
        version="test",
        log_info=lambda *args, **kwargs: None,
        log_debug=lambda *args, **kwargs: None,
    )


def test_unified_lifecycle_bindings():
    assert ub.on_startup.__module__ == "arena.lifecycle"
    assert ub.on_cleanup.__module__ == "arena.lifecycle"
    assert ub._signal_handler.__module__ == "arena.lifecycle"


def test_lifecycle_startup_cleanup_flow():
    events = []
    executor = ThreadPoolExecutor(max_workers=1)
    slow_executor = ThreadPoolExecutor(max_workers=1)
    runtime = make_lifecycle(_ctx(events, executor, slow_executor))
    app = web.Application()
    app[APP_CFG] = {"max_concurrent": 2}

    asyncio.run(runtime.on_startup(app))
    assert "init_memory" in events
    assert "start_watchdog" in events
    assert app.get(APP_TASK_RUNNER) is not None
    assert app.get(APP_LOG_CLEANUP) is not None
    assert app[APP_CFG]["semaphore"]

    asyncio.run(runtime.on_cleanup(app))
    assert "stop_watchdog" in events
    assert "stop_cdp" in events
    assert "stop_grpc" in events
    assert "stop_cluster" in events
