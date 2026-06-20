"""Application startup/cleanup and signal lifecycle helpers."""
from __future__ import annotations

import asyncio
import os
import shutil
import signal
import threading
from collections.abc import Callable
from concurrent.futures import Executor
from dataclasses import dataclass
from typing import Any

from aiohttp import web
from arena.app_keys import APP_CFG, APP_TASK_RUNNER, APP_LOG_CLEANUP, APP_FILE_WATCH_LOOP


@dataclass(frozen=True)
class LifecycleContext:
    executor: Executor
    slow_executor: Executor
    init_memory_db: Callable[[], None]
    task_runner_loop: Callable[[web.Application], Any]
    log_cleanup_loop: Callable[[web.Application], Any]
    file_watch_loop: Callable[[web.Application], Any]
    start_watchdog: Callable[[], None]
    stop_watchdog: Callable[[], None]
    stop_cdp_watcher: Callable[[], None]
    cdp_state: dict[str, Any]
    stop_grpc_server: Callable[[], Any]
    stop_cluster_heartbeat: Callable[[], Any]
    get_shutdown_event: Callable[[], asyncio.Event | None]
    version: str
    log_info: Callable[..., None]
    log_debug: Callable[..., None]


@dataclass(frozen=True)
class LifecycleRuntime:
    on_startup: Callable[[web.Application], Any]
    on_cleanup: Callable[[web.Application], Any]
    signal_handler: Callable[[int, Any], None]


def make_lifecycle(ctx: LifecycleContext) -> LifecycleRuntime:
    async def on_startup(app: web.Application):
        """Start background task runner and initialize async primitives."""
        await asyncio.get_running_loop().run_in_executor(ctx.executor, ctx.init_memory_db)

        cfg = app[APP_CFG]
        cfg["semaphore"] = asyncio.Semaphore(cfg["max_concurrent"])
        app[APP_TASK_RUNNER] = asyncio.ensure_future(ctx.task_runner_loop(app))
        app[APP_LOG_CLEANUP] = asyncio.ensure_future(ctx.log_cleanup_loop(app))
        app[APP_FILE_WATCH_LOOP] = asyncio.ensure_future(ctx.file_watch_loop(app))
        ctx.start_watchdog()

        if shutil.which("ydotoold") and hasattr(os, "getuid") and not os.path.exists("/run/user/%d/.ydotool_socket" % os.getuid()):
            try:
                proc = await asyncio.create_subprocess_exec(
                    "ydotoold",
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                ctx.log_info("[Desktop] ydotoold started (PID %d) for Wayland automation", proc.pid)
            except Exception as e:
                ctx.log_debug("[Desktop] Could not start ydotoold (non-fatal): %s", e)
        ctx.log_info("[UnifiedBridge v%s] Background task runner + watchdog + log cleanup started", ctx.version)

    async def on_cleanup(app: web.Application):
        """Stop background task runner and clean up resources."""
        tr = app.get(APP_TASK_RUNNER)
        if tr:
            tr.cancel()
            try:
                await tr
            except asyncio.CancelledError:
                pass

        lc = app.get(APP_LOG_CLEANUP)
        if lc:
            lc.cancel()
            try:
                await lc
            except asyncio.CancelledError:
                pass

        fw = app.get(APP_FILE_WATCH_LOOP)
        if fw:
            fw.cancel()
            try:
                await fw
            except asyncio.CancelledError:
                pass

        try:
            ctx.stop_watchdog()
        except Exception:
            pass

        try:
            ctx.stop_cdp_watcher()
        except Exception:
            pass

        try:
            if ctx.cdp_state.get("manager"):
                await asyncio.wait_for(ctx.cdp_state["manager"].close(), timeout=10)
        except Exception:
            pass

        await ctx.stop_grpc_server()
        await ctx.stop_cluster_heartbeat()

        ctx.executor.shutdown(wait=False)
        ctx.slow_executor.shutdown(wait=False)

    def signal_handler(sig: int, frame: Any) -> None:
        """Signal handler for graceful shutdown."""
        sig_name = signal.Signals(sig).name if hasattr(signal, "Signals") else str(sig)
        ctx.log_info("[UnifiedBridge] Received %s, shutting down gracefully...", sig_name)

        try:
            ctx.stop_watchdog()
        except Exception:
            pass

        try:
            ctx.stop_cdp_watcher()
        except Exception:
            pass

        try:
            if ctx.cdp_state.get("manager"):
                mgr = ctx.cdp_state["manager"]
                if mgr._browser_proc and mgr._browser_proc.poll() is None:
                    mgr._browser_proc.terminate()
                    try:
                        mgr._browser_proc.wait(timeout=3)
                    except Exception:
                        mgr._browser_proc.kill()
        except Exception:
            pass

        shutdown_event = ctx.get_shutdown_event()
        if shutdown_event is not None:
            shutdown_event.set()
        threading.Timer(5.0, lambda: os._exit(0)).start()

    return LifecycleRuntime(on_startup=on_startup, on_cleanup=on_cleanup, signal_handler=signal_handler)
