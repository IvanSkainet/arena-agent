"""CDP runtime state, module loading, and background health watchers."""
from __future__ import annotations

import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from typing import Any, Optional

from arena.constants import BRIDGE_DIR

log = logging.getLogger("arena-bridge")

# ============================================================================
# CDP (Chrome DevTools Protocol) — Lazy import & session state
# ============================================================================
_cdp_module = None

def _get_cdp_module():
    """Lazily import cdp_browser from scripts/ directory."""
    global _cdp_module
    if _cdp_module is not None:
        return _cdp_module

    # Try multiple locations for cdp_browser.py
    search_paths = [
        BRIDGE_DIR / "scripts",
    ]

    for scripts_dir in search_paths:
        cdp_path = scripts_dir / "cdp_browser.py"
        if cdp_path.exists():
            sys.path.insert(0, str(scripts_dir))
            break

    try:
        import cdp_browser
        _cdp_module = cdp_browser

        # Configure the cdp_browser logger to use the same handlers as the bridge logger.
        # Without this, cdp_browser's logger.info/error calls are silently dropped
        # because the "cdp_browser" logger has no handlers configured.
        bridge_logger = logging.getLogger("arena-bridge")
        cdp_logger = logging.getLogger("cdp_browser")
        cdp_logger.setLevel(logging.DEBUG)
        # Clear any existing handlers and copy bridge's handlers
        cdp_logger.handlers.clear()
        for handler in bridge_logger.handlers:
            cdp_logger.addHandler(handler)
        # Don't propagate to root logger (bridge handles it)
        cdp_logger.propagate = False
        log.info("[CDP] Configured cdp_browser logger with %d handler(s)", len(bridge_logger.handlers))

        return _cdp_module
    except ImportError as e:
        return None


# --- CDP Session State ---
_cdp_state: dict[str, Any] = {
    "manager": None,           # CDPTabManager instance
    "monitor": None,           # CDPNetworkMonitor instance
    "interceptor": None,       # CDPNetworkInterceptor instance
    "cookie_mgr": None,        # CDPCookieManager instance
    "connected": False,
    "port": 9222,
    "headless": True,
    "reconnect_count": 0,      # Number of auto-reconnects performed
    "last_connect_time": None, # Timestamp of last successful connect
    "last_disconnect_reason": None,  # Reason for last disconnect
    "last_navigation_time": None,    # Timestamp of last navigate call (skip probes during nav)
    "_consecutive_probe_timeouts": 0, # Tolerate N slow probes before reconnecting
    "_consecutive_none_probes": 0,    # Tolerate N None probes before reconnecting
}

_cdp_connect_lock = asyncio.Lock()  # Prevent concurrent connect/disconnect
_cdp_watcher_task: Optional[asyncio.Task] = None  # Background watcher for auto-reconnect

# --- CDP Event-Loop Blockage Detector (v2.3.0) ---
_cdp_loop_healthy_ts: float = time.time()  # Last time the event loop was responsive
_cdp_loop_check_task: Optional[asyncio.Task] = None
CDP_LOOP_CHECK_INTERVAL = 5.0   # seconds between checks
CDP_LOOP_BLOCK_THRESHOLD = 30.0  # seconds before declaring blocked


# --- CDP Auto-Reconnect Watcher ---
async def _cdp_watcher_loop():
    """Background task that monitors CDP connection health and auto-reconnects.

    Checks every 10 seconds:
    1. Is the browser process still alive?
    2. Is the WebSocket connection still open?
    3. Can we still list tabs?

    If any check fails, attempts to reconnect automatically.
    """
    while True:
        try:
            await asyncio.sleep(10)

            if not _cdp_state["connected"] or _cdp_connect_lock.locked():
                continue

            mgr = _cdp_state.get("manager")
            if not mgr:
                continue

            needs_reconnect = False
            reason = ""

            # Check 1: Browser process alive (only if we launched it)
            if mgr._browser_proc and mgr._browser_proc.poll() is not None:
                needs_reconnect = True
                reason = f"Browser process exited (rc={mgr._browser_proc.returncode})"
                log.warning("[CDP-Watcher] %s", reason)

            # Check 2: Active tab WebSocket still open
            elif mgr.active_tab and not mgr.active_tab.connected:
                # Tab was connected but now isn't — try a quick re-check
                try:
                    cdp_mod = _get_cdp_module()
                    tabs = await asyncio.get_event_loop().run_in_executor(
                        None, cdp_mod.list_tabs, _cdp_state["port"]
                    )
                    if tabs:
                        needs_reconnect = True
                        reason = "Active tab WebSocket disconnected but browser still running"
                        log.warning("[CDP-Watcher] %s", reason)
                    else:
                        needs_reconnect = True
                        reason = "No tabs found — browser may have crashed"
                        log.warning("[CDP-Watcher] %s", reason)
                except Exception as e:
                    needs_reconnect = True
                    reason = f"Cannot reach browser debug port: {e}"
                    log.warning("[CDP-Watcher] %s", reason)

            # Check 3: Health probe — tolerant of heavy pages (v2.5.1: improved resilience)
            elif mgr.active_tab and mgr.active_tab.connected:
                # Skip probe if navigation was recently initiated (heavy page loading)
                last_nav = _cdp_state.get("last_navigation_time")
                if last_nav and (time.time() - last_nav) < 45:
                    log.debug("[CDP-Watcher] Skipping health probe — recent navigation (%.1fs ago)",
                              time.time() - last_nav)
                else:
                    try:
                        # v2.5.1: Use lighter-weight CDP command instead of eval_js.
                        # Runtime.evaluate runs JS and waits for the result, which can
                        # be blocked by heavy pages doing synchronous JS work. Instead,
                        # use a simple CDP ping (Target.getTargetInfo) that only checks
                        # if the WebSocket is alive without needing JS execution.
                        result = await asyncio.wait_for(
                            mgr.active_tab.send("Target.getTargetInfo"),
                            timeout=10  # 10s — pure WS round-trip, no JS execution
                        )
                        if result is None:
                            _cdp_state["_consecutive_none_probes"] = _cdp_state.get("_consecutive_none_probes", 0) + 1
                            if _cdp_state["_consecutive_none_probes"] >= 3:
                                needs_reconnect = True
                                reason = f"Health probe returned None {_cdp_state['_consecutive_none_probes']}x — WS likely stale"
                                log.warning("[CDP-Watcher] %s", reason)
                            else:
                                log.debug("[CDP-Watcher] Health probe None (%d/3 tolerated)",
                                          _cdp_state["_consecutive_none_probes"])
                        else:
                            _cdp_state["_consecutive_none_probes"] = 0
                            _cdp_state["_consecutive_probe_timeouts"] = 0
                    except asyncio.TimeoutError:
                        # v2.5.1: More tolerant — WS ping timing out once is not fatal.
                        # Heavy pages may block the CDP message loop briefly.
                        _cdp_state["_consecutive_probe_timeouts"] = _cdp_state.get("_consecutive_probe_timeouts", 0) + 1
                        if _cdp_state["_consecutive_probe_timeouts"] >= 3:
                            needs_reconnect = True
                            reason = f"Health probe timed out {_cdp_state['_consecutive_probe_timeouts']}x consecutively (10s each)"
                            log.warning("[CDP-Watcher] %s", reason)
                        else:
                            log.info("[CDP-Watcher] Health probe timed out (%d/3 tolerated) — heavy page?",
                                     _cdp_state["_consecutive_probe_timeouts"])
                    except ConnectionError:
                        needs_reconnect = True
                        reason = "Health probe got ConnectionError — WebSocket closed"
                        log.warning("[CDP-Watcher] %s", reason)
                    except Exception as e:
                        # v2.5.1: Some CDP errors (e.g. Target domain not available)
                        # are non-fatal. Only reconnect on consecutive failures.
                        _cdp_state["_consecutive_probe_errors"] = _cdp_state.get("_consecutive_probe_errors", 0) + 1
                        if _cdp_state["_consecutive_probe_errors"] >= 3:
                            needs_reconnect = True
                            reason = f"Health probe error {_cdp_state['_consecutive_probe_errors']}x: {e}"
                            log.warning("[CDP-Watcher] %s", reason)
                        else:
                            log.debug("[CDP-Watcher] Health probe error (%d/3 tolerated): %s",
                                      _cdp_state["_consecutive_probe_errors"], e)

            if needs_reconnect:
                log.info("[CDP-Watcher] Initiating auto-reconnect... reason: %s", reason)
                _cdp_state["last_disconnect_reason"] = reason

                # Try to gracefully close existing connection
                try:
                    if mgr:
                        await asyncio.wait_for(mgr.close(), timeout=5)
                except Exception as e:
                    log.warning("[CDP-Watcher] Close failed (non-fatal): %s", e)

                _cdp_state["connected"] = False
                _cdp_state["manager"] = None

                # Auto-reconnect
                try:
                    cdp = _get_cdp_module()
                    if cdp:
                        new_mgr = cdp.CDPTabManager(
                            port=_cdp_state["port"],
                            headless=_cdp_state["headless"],
                            auto_launch=True,
                        )
                        await asyncio.wait_for(new_mgr.connect(), timeout=60)
                        _cdp_state["manager"] = new_mgr
                        _cdp_state["connected"] = True
                        _cdp_state["reconnect_count"] += 1
                        _cdp_state["last_connect_time"] = datetime.now(timezone.utc).isoformat()
                        log.info("[CDP-Watcher] Auto-reconnect SUCCESSFUL (count=%d)",
                                 _cdp_state["reconnect_count"])
                    else:
                        log.error("[CDP-Watcher] Cannot reconnect: cdp_browser module not found")
                except asyncio.TimeoutError:
                    log.error("[CDP-Watcher] Auto-reconnect TIMED OUT (60s)")
                    _cdp_state["connected"] = False
                except Exception as e:
                    log.error("[CDP-Watcher] Auto-reconnect FAILED: %s", e)
                    _cdp_state["connected"] = False

        except asyncio.CancelledError:
            log.info("[CDP-Watcher] Cancelled — shutting down")
            break
        except Exception as e:
            log.error("[CDP-Watcher] Unexpected error: %s", e)


async def _cdp_loop_blockage_detector():
    """Detect when the asyncio event loop is blocked for too long (v2.3.0).

    Uses a simple liveness pattern: schedule a callback from the event loop
    and measure how long it actually takes to run. If the loop is blocked
    (e.g., by a hanging CDP operation), the callback will be delayed.
    Logs a CRITICAL warning if blocked > threshold seconds.
    """
    global _cdp_loop_healthy_ts
    while True:
        try:
            loop = asyncio.get_running_loop()
            start = time.monotonic()

            fut = loop.create_future()
            loop.call_soon(lambda: fut.set_result(None) if not fut.done() else None)
            await asyncio.wait_for(fut, timeout=5.0)

            delay = time.monotonic() - start
            _cdp_loop_healthy_ts = time.time()

            if delay > 2.0:
                log.warning("[CDP-LoopCheck] Event loop delayed %.2fs (threshold: 2s)", delay)

        except asyncio.TimeoutError:
            blocked_for = time.time() - _cdp_loop_healthy_ts
            log.critical(
                "[CDP-LoopCheck] EVENT LOOP APPEARS BLOCKED for %.1fs! "
                "This likely indicates a hanging CDP operation. "
                "Last healthy: %.1fs ago",
                blocked_for, time.time() - _cdp_loop_healthy_ts
            )
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("[CDP-LoopCheck] Unexpected error: %s", e)

        await asyncio.sleep(CDP_LOOP_CHECK_INTERVAL)


def _start_cdp_watcher():
    """Start the CDP health watcher and loop blockage detector."""
    global _cdp_watcher_task, _cdp_loop_check_task
    if _cdp_watcher_task and not _cdp_watcher_task.done():
        return
    _cdp_watcher_task = asyncio.create_task(_cdp_watcher_loop())
    # Start event-loop blockage detector
    if not _cdp_loop_check_task or _cdp_loop_check_task.done():
        _cdp_loop_check_task = asyncio.create_task(_cdp_loop_blockage_detector())
    log.info("[CDP-Watcher] Started (with loop blockage detector)")


def _stop_cdp_watcher():
    """Stop the CDP health watcher and loop blockage detector."""
    global _cdp_watcher_task, _cdp_loop_check_task
    if _cdp_watcher_task and not _cdp_watcher_task.done():
        _cdp_watcher_task.cancel()
        _cdp_watcher_task = None
    if _cdp_loop_check_task and not _cdp_loop_check_task.done():
        _cdp_loop_check_task.cancel()
        _cdp_loop_check_task = None
    log.info("[CDP-Watcher] Stopped (including loop blockage detector)")




def cdp_watcher_active() -> bool:
    """Return True when the CDP watcher task is currently running."""
    return _cdp_watcher_task is not None and not _cdp_watcher_task.done()
