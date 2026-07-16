"""Handlers for the Arena Web Gateway endpoints."""
from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass

from aiohttp import web

from arena.gateway.runtime import GW_WHITELIST, gw_allowed, gw_run_sync
from arena.handler_context import GatewayHandlerContext
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class GatewayHandlers:
    index: object
    tools: object
    run: object
    tool: object


def make_gateway_handlers(ctx: GatewayHandlerContext) -> GatewayHandlers:
    async def handle_gateway_index(request: web.Request) -> web.Response:
        try:
            r = ctx.require_auth(request)
            if r:
                return r
            ctx.record_request()
            return ctx.cors_json_response({
                "ok": True,
                "service": "arena-web-gateway",
                "version": "1.0.0",
                "endpoints": ["/gateway", "/gateway/tools", "/run (POST)", "/tool (POST)"],
                "mcp_proxy": "/mcp",
                "auth_required": True,
            })
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_gateway_tools(request: web.Request) -> web.Response:
        try:
            r = ctx.require_auth(request)
            if r:
                return r
            ctx.record_request()
            mcp_tools = ctx.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            return ctx.cors_json_response({
                "ok": True,
                "whitelist_prefixes": list(GW_WHITELIST),
                "mcp_tools": mcp_tools.get("result", {}).get("tools", []) if mcp_tools else [],
            })
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    @authed(ctx)
    async def handle_gateway_run(request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "bad json"}, status=400)
        cmd = (data.get("command") or data.get("cmd") or "").strip()
        if not cmd:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing command"}, status=400)
        if not gw_allowed(cmd):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({
                "ok": False,
                "error": "command not in whitelist",
                "allowed": list(GW_WHITELIST),
            }, status=403)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            functools.partial(
                gw_run_sync,
                cmd,
                int(data.get("timeout", 60)),
                subprocess_kwargs=ctx.subprocess_kwargs,
            ),
        )
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_gateway_tool(request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "bad json"}, status=400)
        name = data.get("name")
        # Support both "arguments" (MCP spec) and "input" (common alternative)
        args = data.get("arguments") or data.get("input") or {}
        if not name:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing tool name"}, status=400)
        resp = ctx.handle_rpc({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        })
        return ctx.cors_json_response({"ok": "error" not in (resp or {}), "response": resp})

    return GatewayHandlers(
        index=handle_gateway_index,
        tools=handle_gateway_tools,
        run=handle_gateway_run,
        tool=handle_gateway_tool,
    )
