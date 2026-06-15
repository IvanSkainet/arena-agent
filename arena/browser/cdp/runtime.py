"""CDP runtime state, module loading, and background health watcher facade."""
from __future__ import annotations

from arena.browser.cdp.loader import _get_cdp_module
from arena.browser.cdp.state import (
    CDP_LOOP_BLOCK_THRESHOLD,
    CDP_LOOP_CHECK_INTERVAL,
    _cdp_connect_lock,
    _cdp_loop_check_task,
    _cdp_loop_healthy_ts,
    _cdp_state,
    _cdp_watcher_task,
)
from arena.browser.cdp.runtime_loop import _cdp_loop_blockage_detector
from arena.browser.cdp.runtime_watcher import (
    _cdp_watcher_loop,
    _start_cdp_watcher,
    _stop_cdp_watcher,
    cdp_watcher_active,
)

__all__ = [
    "CDP_LOOP_BLOCK_THRESHOLD",
    "CDP_LOOP_CHECK_INTERVAL",
    "_cdp_connect_lock",
    "_cdp_loop_blockage_detector",
    "_cdp_loop_check_task",
    "_cdp_loop_healthy_ts",
    "_cdp_state",
    "_cdp_watcher_loop",
    "_cdp_watcher_task",
    "_get_cdp_module",
    "_start_cdp_watcher",
    "_stop_cdp_watcher",
    "cdp_watcher_active",
]
