"""Bridge request metrics state and helpers."""
from __future__ import annotations

import threading
import time
from typing import Any

BRIDGE_METRICS: dict[str, Any] = {
    "total_requests": 0,
    "total_exec": 0,
    "total_errors": 0,
    "start_time": time.time(),
    "request_durations": [],
}
_metrics_lock = threading.Lock()


def record_request(
    duration: float = 0.0,
    is_exec: bool = False,
    is_error: bool = False,
    count_request: bool = True,
) -> None:
    """Record a request/exec/error in bridge metrics."""
    with _metrics_lock:
        if count_request:
            BRIDGE_METRICS["total_requests"] += 1
        if is_exec:
            BRIDGE_METRICS["total_exec"] += 1
        if is_error:
            BRIDGE_METRICS["total_errors"] += 1
        if duration > 0:
            BRIDGE_METRICS["request_durations"].append(duration)
            if len(BRIDGE_METRICS["request_durations"]) > 1000:
                BRIDGE_METRICS["request_durations"] = BRIDGE_METRICS["request_durations"][-1000:]


# Backward-compatible private name used by unified_bridge.py.
_record_request = record_request
