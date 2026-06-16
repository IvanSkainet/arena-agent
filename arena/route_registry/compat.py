"""Compatibility, v2, tracing, GUI, MCP and gateway route registration."""
from __future__ import annotations

from collections.abc import Callable, Mapping

from aiohttp import web


def register_compat_routes(app: web.Application, h: Mapping[str, Callable]) -> None:
    app.router.add_get("/v2/", h["handle_v2_index"])
    app.router.add_get("/v2/status", h["handle_v2_status"])
    app.router.add_get("/v2/health", h["handle_v2_health"])
    app.router.add_get("/v2/browser/status", h["handle_v2_browser_status"])
    app.router.add_post("/v2/exec", h["handle_v2_exec"])
    app.router.add_get("/v2/deprecations", h["handle_v2_deprecations"])

    app.router.add_get("/v1/tracing", h["handle_v1_tracing"])
    app.router.add_post("/v1/tracing", h["handle_v1_tracing"])
    app.router.add_get("/v1/traces/export", h["handle_v1_traces_export"])
    app.router.add_post("/v1/traces/export", h["handle_v1_traces_export"])

    app.router.add_get("/gui", h["handle_gui"])
    app.router.add_post("/mcp", h["handle_mcp_post"])
    app.router.add_delete("/mcp", h["handle_mcp_delete"])
    app.router.add_get("/sse", h["handle_sse"])
    app.router.add_post("/messages", h["handle_sse_messages"])
    app.router.add_get("/ws", h["handle_ws"])
    app.router.add_get("/gateway", h["handle_gateway_index"])
    app.router.add_get("/gateway/tools", h["handle_gateway_tools"])
    app.router.add_post("/run", h["handle_gateway_run"])
    app.router.add_post("/tool", h["handle_gateway_tool"])
