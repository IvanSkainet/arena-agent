"""OpenTelemetry-style trace ID, sampling and span recording helpers."""
from __future__ import annotations

import random
import secrets

from arena.constants import VERSION
from arena.observability import tracing_state as state
from arena.util import utc_now


def _otel_trace_id() -> str:
    """Generate a trace ID."""
    state._otel_trace_counter += 1
    return f"{state._otel_trace_counter:016x}{secrets.token_hex(8)}"


def _otel_record_span(
    trace_id: str,
    span_id: str,
    name: str,
    duration_ms: float,
    attributes: dict | None = None,
    parent_span_id: str = "",
    status: str = "OK",
) -> None:
    """Record an OpenTelemetry span."""
    span = {
        "trace_id": trace_id,
        "span_id": span_id,
        "name": name,
        "kind": "SERVER",
        "start_time": utc_now(),
        "duration_ms": round(duration_ms, 2),
        "status": status,
        "attributes": attributes or {},
        "resource": {
            "service.name": state._otel_config["service_name"],
            "service.version": VERSION,
        },
    }
    if parent_span_id:
        span["parent_span_id"] = parent_span_id

    with state._otel_lock:
        state._otel_traces.append(span)
        if len(state._otel_traces) > state._otel_config["max_spans"]:
            state._otel_traces[:] = state._otel_traces[-state._otel_config["max_spans"]:]


def _otel_should_sample() -> bool:
    """Decide if this request should be traced."""
    if not state._otel_config["enabled"]:
        return False
    return random.random() < state._otel_config["sample_rate"]
