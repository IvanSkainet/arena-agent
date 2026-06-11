"""Health watchdog runtime state and loop."""
from __future__ import annotations

import asyncio
import sys
import time
from collections.abc import Awaitable, Callable
from typing import Any

WATCHDOG_STATE: dict[str, Any] = {
    "last_check": 0.0,
    "memory_mb": 0.0,
    "cpu_percent": 0.0,
    "alerts": [],
    "restart_count": 0,
    "auto_restart": True,
    "memory_limit_mb": 512,
    "cpu_limit_percent": 90.0,
    "check_interval_s": 30,
}
_WATCHDOG_TASK: asyncio.Task | None = None


async def watchdog_loop(
    *,
    utc_now_fn: Callable[[], str],
    emit_event_fn: Callable[[str, dict | None], Awaitable[None]],
    log_info: Callable[..., None] | None = None,
    log_warning: Callable[..., None] | None = None,
    log_error: Callable[..., None] | None = None,
) -> None:
    """Background watchdog that monitors bridge health and emits alerts."""
    while True:
        try:
            await asyncio.sleep(WATCHDOG_STATE["check_interval_s"])

            # Memory and CPU monitoring.
            mem_mb = 0.0
            cpu_pct = 0.0
            try:
                import psutil  # type: ignore
                proc = psutil.Process()
                mem_info = proc.memory_info()
                mem_mb = mem_info.rss / (1024 * 1024)
                cpu_pct = proc.cpu_percent(interval=1.0)
            except ImportError:
                # Fallback: read from /proc/self/status on Linux.
                try:
                    if sys.platform != "win32":
                        with open("/proc/self/status") as f:
                            for line in f:
                                if line.startswith("VmRSS:"):
                                    mem_mb = int(line.split()[1]) / 1024  # kB to MB
                                    break
                except Exception:
                    pass
            except Exception:
                pass

            WATCHDOG_STATE["memory_mb"] = round(mem_mb, 1)
            WATCHDOG_STATE["cpu_percent"] = round(cpu_pct, 1)
            WATCHDOG_STATE["last_check"] = time.time()

            # Check thresholds and emit alerts.
            alerts_now: list[dict[str, Any]] = []
            if mem_mb > WATCHDOG_STATE["memory_limit_mb"]:
                alert = {"type": "memory_high", "value_mb": round(mem_mb, 1),
                         "limit_mb": WATCHDOG_STATE["memory_limit_mb"],
                         "ts": utc_now_fn()}
                alerts_now.append(alert)
                if log_warning:
                    log_warning("[Watchdog] Memory alert: %.1f MB > %.0f MB limit",
                                mem_mb, WATCHDOG_STATE["memory_limit_mb"])
                await emit_event_fn("alert", alert)

            if cpu_pct > WATCHDOG_STATE["cpu_limit_percent"]:
                alert = {"type": "cpu_high", "value_pct": round(cpu_pct, 1),
                         "limit_pct": WATCHDOG_STATE["cpu_limit_percent"],
                         "ts": utc_now_fn()}
                alerts_now.append(alert)
                if log_warning:
                    log_warning("[Watchdog] CPU alert: %.1f%% > %.1f%% limit",
                                cpu_pct, WATCHDOG_STATE["cpu_limit_percent"])
                await emit_event_fn("alert", alert)

            # Keep last 50 alerts.
            WATCHDOG_STATE["alerts"].extend(alerts_now)
            WATCHDOG_STATE["alerts"] = WATCHDOG_STATE["alerts"][-50:]

        except asyncio.CancelledError:
            if log_info:
                log_info("[Watchdog] Cancelled — shutting down")
            break
        except Exception as e:
            if log_error:
                log_error("[Watchdog] Unexpected error: %s", e)
            await asyncio.sleep(10)


def start_watchdog(
    *,
    utc_now_fn: Callable[[], str],
    emit_event_fn: Callable[[str, dict | None], Awaitable[None]],
    log_info: Callable[..., None] | None = None,
    log_warning: Callable[..., None] | None = None,
    log_error: Callable[..., None] | None = None,
) -> None:
    """Start the health watchdog if not already running."""
    global _WATCHDOG_TASK
    if _WATCHDOG_TASK and not _WATCHDOG_TASK.done():
        return
    _WATCHDOG_TASK = asyncio.create_task(watchdog_loop(
        utc_now_fn=utc_now_fn,
        emit_event_fn=emit_event_fn,
        log_info=log_info,
        log_warning=log_warning,
        log_error=log_error,
    ))
    if log_info:
        log_info("[Watchdog] Started (interval=%ds, mem_limit=%dMB, cpu_limit=%.0f%%)",
                 WATCHDOG_STATE["check_interval_s"],
                 WATCHDOG_STATE["memory_limit_mb"],
                 WATCHDOG_STATE["cpu_limit_percent"])


def stop_watchdog(*, log_info: Callable[..., None] | None = None) -> None:
    """Stop the health watchdog."""
    global _WATCHDOG_TASK
    if _WATCHDOG_TASK and not _WATCHDOG_TASK.done():
        _WATCHDOG_TASK.cancel()
        _WATCHDOG_TASK = None
        if log_info:
            log_info("[Watchdog] Stopped")
