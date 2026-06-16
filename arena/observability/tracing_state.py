"""OpenTelemetry-style tracing state singletons."""
from __future__ import annotations

import threading
from typing import Any

_otel_config: dict[str, Any] = {
    "enabled": False,
    "service_name": "arena-bridge",
    "endpoint": "",
    "sample_rate": 1.0,
    "max_spans": 1000,
}
_otel_traces: list[dict[str, Any]] = []
_otel_lock = threading.Lock()
_otel_trace_counter: int = 0
