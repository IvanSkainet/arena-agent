"""OpenTelemetry-style in-memory tracing helpers and API handlers."""
from __future__ import annotations

import random
import secrets
import threading
from dataclasses import dataclass
from typing import Any

import aiohttp
from aiohttp import web

from arena.constants import VERSION
from arena.handler_context import TracingHandlerContext
from arena.util import utc_now

_otel_config: dict[str, Any] = {
    "enabled": False,
    "service_name": "arena-bridge",
    "endpoint": "",       # OTLP endpoint (e.g., "http://localhost:4318/v1/traces")
    "sample_rate": 1.0,   # 0.0 to 1.0
    "max_spans": 1000,
}
_otel_traces: list[dict[str, Any]] = []
_otel_lock = threading.Lock()
_otel_trace_counter: int = 0


@dataclass(frozen=True)
class TracingHandlers:
    tracing: object
    traces_export: object


def _otel_trace_id() -> str:
    """Generate a trace ID."""
    global _otel_trace_counter
    _otel_trace_counter += 1
    return f"{_otel_trace_counter:016x}{secrets.token_hex(8)}"


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
            "service.name": _otel_config["service_name"],
            "service.version": VERSION,
        },
    }
    if parent_span_id:
        span["parent_span_id"] = parent_span_id

    with _otel_lock:
        _otel_traces.append(span)
        if len(_otel_traces) > _otel_config["max_spans"]:
            _otel_traces[:] = _otel_traces[-_otel_config["max_spans"]:]


def _otel_should_sample() -> bool:
    """Decide if this request should be traced."""
    if not _otel_config["enabled"]:
        return False
    return random.random() < _otel_config["sample_rate"]


def make_tracing_handlers(ctx: TracingHandlerContext) -> TracingHandlers:
    async def handle_v1_tracing(request: web.Request) -> web.Response:
        """GET /v1/tracing — OpenTelemetry tracing configuration and recent traces.
        POST /v1/tracing — Configure tracing.
        """
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        if request.method == "POST":
            try:
                data = await request.json()
                if "enabled" in data:
                    _otel_config["enabled"] = bool(data["enabled"])
                if "service_name" in data:
                    _otel_config["service_name"] = str(data["service_name"])
                if "endpoint" in data:
                    _otel_config["endpoint"] = str(data["endpoint"])
                if "sample_rate" in data:
                    _otel_config["sample_rate"] = max(0.0, min(1.0, float(data["sample_rate"])))
                if "max_spans" in data:
                    _otel_config["max_spans"] = max(10, int(data["max_spans"]))
                ctx.log_info(
                    "[OTel] Configuration updated: enabled=%s, endpoint=%s, sample_rate=%.2f",
                    _otel_config["enabled"], _otel_config["endpoint"], _otel_config["sample_rate"],
                )
            except Exception as e:
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)

        # Return config + recent traces
        with _otel_lock:
            recent_traces = list(_otel_traces[-50:])
            trace_count = len(_otel_traces)

        return ctx.cors_json_response({
            "ok": True,
            "config": _otel_config,
            "recent_traces": trace_count,
            "traces": recent_traces,
        })

    async def handle_v1_traces_export(request: web.Request) -> web.Response:
        """POST /v1/traces/export — Export traces in OTLP JSON format.
        GET /v1/traces/export — Get all stored traces.
        """
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        if request.method == "POST":
            # Export to configured OTLP endpoint
            if not _otel_config["endpoint"]:
                return ctx.cors_json_response({"ok": False, "error": "no OTLP endpoint configured"}, status=400)

            with _otel_lock:
                traces = list(_otel_traces)

            if not traces:
                return ctx.cors_json_response({"ok": True, "exported": 0, "message": "no traces to export"})

            # Build OTLP JSON payload
            otlp_payload = {
                "resourceSpans": [{
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": _otel_config["service_name"]}},
                            {"key": "service.version", "value": {"stringValue": ctx.version}},
                        ]
                    },
                    "scopeSpans": [{
                        "scope": {"name": "arena-bridge"},
                        "spans": traces,
                    }]
                }]
            }

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        _otel_config["endpoint"],
                        json=otlp_payload,
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        exported = len(traces)
                        if resp.status < 400:
                            # Clear exported traces
                            with _otel_lock:
                                _otel_traces.clear()
                            return ctx.cors_json_response({"ok": True, "exported": exported})
                        return ctx.cors_json_response({
                            "ok": False,
                            "error": f"OTLP endpoint returned {resp.status}",
                            "exported": 0,
                        }, status=502)
            except Exception as e:
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=502)

        # GET: return all traces
        with _otel_lock:
            all_traces = list(_otel_traces)

        return ctx.cors_json_response({
            "ok": True,
            "total": len(all_traces),
            "traces": all_traces,
        })

    return TracingHandlers(tracing=handle_v1_tracing, traces_export=handle_v1_traces_export)
