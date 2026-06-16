"""JSON runtime metrics handler."""
from __future__ import annotations

from aiohttp import web

from arena.handler_context import RuntimeObservabilityHandlerContext
from arena.observability.runtime_common import metrics_snapshot


def make_metrics_handler(ctx: RuntimeObservabilityHandlerContext):
    async def handle_v1_metrics(request: web.Request) -> web.Response:
        """GET /v1/metrics — Bridge performance metrics."""
        try:
            ctx.record_request()
            snap = metrics_snapshot(ctx)
            return ctx.cors_json_response({
                "ok": True,
                "uptime_seconds": snap["uptime"],
                "total_requests": snap["total_requests"],
                "total_exec": snap["total_exec"],
                "total_errors": snap["total_errors"],
                "average_duration_sec": snap["avg_duration"],
                "error_rate_percent": snap["error_rate"],
                "start_time": snap["start_time"],
                "version": ctx.version,
                "active_processes": len(ctx.active_processes),
            })
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return handle_v1_metrics
