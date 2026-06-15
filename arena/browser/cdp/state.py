"""CDP runtime state singletons."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

_cdp_state: dict[str, Any] = {
    "manager": None,
    "monitor": None,
    "interceptor": None,
    "cookie_mgr": None,
    "connected": False,
    "port": 9222,
    "headless": True,
    "reconnect_count": 0,
    "last_connect_time": None,
    "last_disconnect_reason": None,
    "last_navigation_time": None,
    "_consecutive_probe_timeouts": 0,
    "_consecutive_none_probes": 0,
}

_cdp_connect_lock = asyncio.Lock()
_cdp_watcher_task: Optional[asyncio.Task] = None
_cdp_loop_healthy_ts: float = time.time()
_cdp_loop_check_task: Optional[asyncio.Task] = None

CDP_LOOP_CHECK_INTERVAL = 5.0
CDP_LOOP_BLOCK_THRESHOLD = 30.0
