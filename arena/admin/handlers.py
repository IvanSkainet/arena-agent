"""Handlers for token regeneration and tunnel/funnel administration."""
from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass

from aiohttp import web

from arena.admin.runtime import cloudflared_funnel_action, sys_funnel_status, tailscale_funnel_action, token_regenerate
from arena.handler_context import AdminHandlerContext


@dataclass(frozen=True)
class AdminHandlers:
    sys_funnel: object
    token_regenerate: object
    tailscale_funnel: object
    cloudflared_tunnel: object


def make_admin_handlers(ctx: AdminHandlerContext) -> AdminHandlers:
    async def handle_v1_sys_funnel(request: web.Request) -> web.Response:
        """GET /v1/sys/funnel — Tailscale Funnel status."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(ctx.executor, functools.partial(sys_funnel_status, subprocess_kwargs=ctx.subprocess_kwargs))
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_token_regenerate(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        cfg = request.app["cfg"]
        target = str(cfg.get("token_file") or "")
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                ctx.executor,
                lambda: token_regenerate(target, default_token_file=ctx.default_token_file),
            )
            if result.get("ok") and result.get("token"):
                cfg["token"] = result["token"]
            ctx.audit({"type": "token_regenerated", "files": result.get("written_to", [])})
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_tailscale_funnel(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        action = request.match_info.get("action", "status")
        cfg = request.app["cfg"]
        port = cfg.get("port", 8765)
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(ctx.executor, tailscale_funnel_action, action, port)
            ctx.audit({"type": "tailscale_funnel", "action": action, "ok": result.get("ok")})
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_cloudflared_tunnel(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        action = request.match_info.get("action", "status")
        cfg = request.app["cfg"]
        port = cfg.get("port", 8765)
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                ctx.executor,
                lambda: cloudflared_funnel_action(
                    action,
                    port,
                    root_agent=ctx.root_agent,
                    subprocess_kwargs=ctx.subprocess_kwargs,
                ),
            )
            ctx.audit({"type": "cloudflared_tunnel", "action": action, "ok": result.get("ok")})
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return AdminHandlers(
        sys_funnel=handle_v1_sys_funnel,
        token_regenerate=handle_v1_token_regenerate,
        tailscale_funnel=handle_v1_tailscale_funnel,
        cloudflared_tunnel=handle_v1_cloudflared_tunnel,
    )
