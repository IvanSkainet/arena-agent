"""CDP background health watcher and watcher task lifecycle."""
from __future__ import annotations

import asyncio
import logging
import time

from arena.browser.cdp.loader import _get_cdp_module
from arena.browser.cdp.runtime_loop import _cdp_loop_blockage_detector
from arena.browser.cdp.runtime_reconnect import auto_reconnect_cdp
from arena.browser.cdp.state import (
    _cdp_connect_lock,
    _cdp_loop_check_task,
    _cdp_state,
    _cdp_watcher_task,
)

log = logging.getLogger("arena-bridge")


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
                    tabs = await asyncio.get_running_loop().run_in_executor(
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
                await auto_reconnect_cdp(mgr, reason)

        except asyncio.CancelledError:
            log.info("[CDP-Watcher] Cancelled — shutting down")
            break
        except Exception as e:
            log.error("[CDP-Watcher] Unexpected error: %s", e)


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
