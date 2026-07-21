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
from arena.app_keys import APP_CFG, APP_TASK_RUNNER, APP_LOG_CLEANUP, APP_FILE_WATCH_LOOP, APP_MISSION_SCHEDULE_LOOP


@dataclass(frozen=True)
class LifecycleContext:
    executor: Executor
    slow_executor: Executor
    init_memory_db: Callable[[], None]
    task_runner_loop: Callable[[web.Application], Any]
    log_cleanup_loop: Callable[[web.Application], Any]
    file_watch_loop: Callable[[web.Application], Any]
    get_mission_schedule_loop: Callable[[], Callable[[web.Application], Any] | None]
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
    # v4.60.2: promoted autostart errors from log_debug to log_warning
    # so Windows operators can see failures without --verbose.
    log_warning: Callable[..., None] | None = None
    # v4.22.1: optional autostart hook for cloudflared. Called in
    # a background executor from on_startup so a slow tunnel spin-
    # up never blocks bridge boot. When None (the default), no
    # autostart is attempted -- preserves pre-v4.22.1 behaviour.
    cloudflared_autostart: Callable[[], Any] | None = None
    # v4.38.0: sibling autostart hooks for ngrok + tailscale.
    # Same shape as cloudflared_autostart -- callable returning
    # an AutostartOutcome-like object (attempted / ok / url /
    # reason / duration_sec). Optional so a wiring context built
    # by older tests keeps working without touching every fixture.
    ngrok_autostart: Callable[[], Any] | None = None
    tailscale_autostart: Callable[[], Any] | None = None
    # v4.47.0: bore as fifth transport -- same shape as ngrok.
    bore_autostart: Callable[[], Any] | None = None


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
        mission_schedule_loop = ctx.get_mission_schedule_loop()
        if mission_schedule_loop is not None:
            app[APP_MISSION_SCHEDULE_LOOP] = asyncio.ensure_future(mission_schedule_loop(app))
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

        # v4.22.1 + v4.38.0: fire autostart hooks in the background
        # for every wired transport. Each hook is a no-op when its
        # marker + env are both unset, so a fresh install pays zero
        # cost. run_in_executor keeps the aiohttp event loop free.
        autostart_hooks = [
            ("Cloudflared", ctx.cloudflared_autostart),
            ("Ngrok",       ctx.ngrok_autostart),
            ("Tailscale",   ctx.tailscale_autostart),
            # v4.47.0: bore as fifth transport.
            ("Bore",        ctx.bore_autostart),
        ]
        for label, hook in autostart_hooks:
            if hook is None:
                # v4.60.2: log-only diagnostic so operators on Windows can
                # see why nothing happened on boot. Previously a wired-but-
                # None hook was silently skipped.
                ctx.log_info("[%s] Autostart hook not wired (skipped)", label)
                continue
            async def _autostart_bg(_label=label, _hook=hook):
                try:
                    outcome = await asyncio.get_running_loop().run_in_executor(
                        ctx.executor, _hook)
                    if outcome is None:
                        # v4.60.2: hook returned None (usually means a
                        # required dependency was not resolved). Surface
                        # it so Windows debugging is possible.
                        ctx.log_info(
                            "[%s] Autostart hook returned None (dependencies not wired?)",
                            _label,
                        )
                        return
                    if not getattr(outcome, "attempted", False):
                        # Marker+env both off. Normal, quiet path.
                        return
                    if outcome.ok:
                        ctx.log_info(
                            "[%s] Autostart OK in %.2fs -- %s",
                            _label, outcome.duration_sec,
                            outcome.url or "(no url yet)",
                        )
                    else:
                        # v4.60.2: was log_info; promoted to log_warning so
                        # it shows in default log filters. Actual failures
                        # should not require --verbose to diagnose.
                        (ctx.log_warning or ctx.log_info)(
                            "[%s] Autostart FAILED: %s (%.2fs)",
                            _label, outcome.reason, outcome.duration_sec,
                        )
                except Exception as e:  # noqa: BLE001
                    # v4.60.2: was log_debug (hidden by default); promoted
                    # to log_warning + include exception type.
                    (ctx.log_warning or ctx.log_info)(
                        "[%s] Autostart raised %s: %s",
                        _label, type(e).__name__, e,
                    )
            asyncio.ensure_future(_autostart_bg())

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

        ms = app.get(APP_MISSION_SCHEDULE_LOOP)
        if ms:
            ms.cancel()
            try:
                await ms
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
