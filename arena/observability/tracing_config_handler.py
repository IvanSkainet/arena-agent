"""Tracing configuration/recent traces handler."""
from __future__ import annotations

from aiohttp import web

from arena.handler_context import TracingHandlerContext
from arena.observability.tracing_state import _otel_config, _otel_lock, _otel_traces


def _update_config(data: dict) -> None:
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


def make_tracing_config_handler(ctx: TracingHandlerContext):
    async def handle_v1_tracing(request: web.Request) -> web.Response:
        """GET/POST /v1/tracing — OpenTelemetry tracing config and recent traces."""
        response = ctx.require_auth(request)
        if response:
            return response
        ctx.record_request()

        if request.method == "POST":
            try:
                data = await request.json()
                _update_config(data)
                ctx.log_info(
                    "[OTel] Configuration updated: enabled=%s, endpoint=%s, sample_rate=%.2f",
                    _otel_config["enabled"], _otel_config["endpoint"], _otel_config["sample_rate"],
                )
            except Exception as e:
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)

        with _otel_lock:
            recent_traces = list(_otel_traces[-50:])
            trace_count = len(_otel_traces)

        return ctx.cors_json_response({
            "ok": True,
            "config": _otel_config,
            "recent_traces": trace_count,
            "traces": recent_traces,
        })

    return handle_v1_tracing
