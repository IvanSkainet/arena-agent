"""CDP watcher auto-reconnect helper."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from arena.browser.cdp.loader import _get_cdp_module
from arena.browser.cdp.state import _cdp_state

log = logging.getLogger("arena-bridge")


async def auto_reconnect_cdp(mgr, reason: str) -> None:
    """Close stale CDP manager and try to reconnect using existing runtime state."""
    log.info("[CDP-Watcher] Initiating auto-reconnect... reason: %s", reason)
    _cdp_state["last_disconnect_reason"] = reason

    try:
        if mgr:
            await asyncio.wait_for(mgr.close(), timeout=5)
    except Exception as e:
        log.warning("[CDP-Watcher] Close failed (non-fatal): %s", e)

    _cdp_state["connected"] = False
    _cdp_state["manager"] = None

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
            log.info(
                "[CDP-Watcher] Auto-reconnect SUCCESSFUL (count=%d)",
                _cdp_state["reconnect_count"],
            )
        else:
            log.error("[CDP-Watcher] Cannot reconnect: cdp_browser module not found")
    except asyncio.TimeoutError:
        log.error("[CDP-Watcher] Auto-reconnect TIMED OUT (60s)")
        _cdp_state["connected"] = False
    except Exception as e:
        log.error("[CDP-Watcher] Auto-reconnect FAILED: %s", e)
        _cdp_state["connected"] = False
