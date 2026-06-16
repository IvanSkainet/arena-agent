"""Tracing export handler."""
from __future__ import annotations

import aiohttp
from aiohttp import web

from arena.handler_context import TracingHandlerContext
from arena.observability.tracing_state import _otel_config, _otel_lock, _otel_traces


def build_otlp_payload(ctx: TracingHandlerContext, traces: list[dict]) -> dict:
    return {
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
            }],
        }]
    }


def make_traces_export_handler(ctx: TracingHandlerContext):
    async def handle_v1_traces_export(request: web.Request) -> web.Response:
        """POST /v1/traces/export — Export traces. GET — return all stored traces."""
        response = ctx.require_auth(request)
        if response:
            return response
        ctx.record_request()

        if request.method == "POST":
            if not _otel_config["endpoint"]:
                return ctx.cors_json_response({"ok": False, "error": "no OTLP endpoint configured"}, status=400)

            with _otel_lock:
                traces = list(_otel_traces)
            if not traces:
                return ctx.cors_json_response({"ok": True, "exported": 0, "message": "no traces to export"})

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(
                        _otel_config["endpoint"],
                        json=build_otlp_payload(ctx, traces),
                        headers={"Content-Type": "application/json"},
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as resp:
                        exported = len(traces)
                        if resp.status < 400:
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

        with _otel_lock:
            all_traces = list(_otel_traces)
        return ctx.cors_json_response({"ok": True, "total": len(all_traces), "traces": all_traces})

    return handle_v1_traces_export
