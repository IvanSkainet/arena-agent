"""Handlers for token regeneration and tunnel/funnel administration.

v3.93.0: Migrated to `@authed` decorator + `err_json` helper from
`arena/handler_helpers.py`. Removes ~110 lines of auth/record/try boilerplate
without changing any wire behaviour — same responses, same status codes,
same audit trail.
"""
from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass

from aiohttp import web
from arena.app_keys import APP_CFG

from arena.admin.runtime import (
    cloudflared_funnel_action,
    sys_funnel_status,
    tailscale_funnel_action,
    token_regenerate,
    zerotier_status,
    zerotier_network_action,
)
from arena.admin.tunnels import tunnels_status, tunnels_active, tunnels_start, tunnels_stop
from arena.handler_context import AdminHandlerContext
from arena.handler_helpers import authed


@dataclass(frozen=True)
class AdminHandlers:
    sys_funnel: object
    token_regenerate: object
    tailscale_funnel: object
    cloudflared_tunnel: object
    zerotier_status: object
    zerotier_network: object
    tunnels_status: object
    tunnels_active: object
    tunnels_start: object
    tunnels_stop: object
    # v3.85.0: cross-platform auto-update.
    update_status: object
    update_check: object
    update_apply: object
    update_restart: object


def make_admin_handlers(ctx: AdminHandlerContext) -> AdminHandlers:
    @authed(ctx)
    async def handle_v1_sys_funnel(request: web.Request) -> web.Response:
        """GET /v1/sys/funnel — Tailscale Funnel status."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            functools.partial(sys_funnel_status, subprocess_kwargs=ctx.subprocess_kwargs),
        )
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_token_regenerate(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]
        target = str(cfg.get("token_file") or "")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            lambda: token_regenerate(target, default_token_file=ctx.default_token_file),
        )
        if result.get("ok") and result.get("token"):
            cfg["token"] = result["token"]
        ctx.audit({"type": "token_regenerated", "files": result.get("written_to", [])})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_tailscale_funnel(request: web.Request) -> web.Response:
        action = request.match_info.get("action", "status")
        cfg = request.app[APP_CFG]
        port = cfg.get("port", 8765)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, tailscale_funnel_action, action, port)
        ctx.audit({"type": "tailscale_funnel", "action": action, "ok": result.get("ok")})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_cloudflared_tunnel(request: web.Request) -> web.Response:
        action = request.match_info.get("action", "status")
        cfg = request.app[APP_CFG]
        port = cfg.get("port", 8765)
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

    @authed(ctx)
    async def handle_v1_zerotier_status(request: web.Request) -> web.Response:
        """GET /v1/zerotier/status — ZeroTier status."""
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            functools.partial(zerotier_status, subprocess_kwargs=ctx.subprocess_kwargs),
        )
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_zerotier_network(request: web.Request) -> web.Response:
        """POST/GET /v1/zerotier/network/{action} — ZeroTier network actions.

        Accepts network_id from any of: URL query string, JSON body, or
        application/x-www-form-urlencoded body — so both curl and browsers
        (Dashboard) can drive it without extra ceremony.
        """
        action = request.match_info.get("action", "status")

        # 1) Always allow ?network_id=... regardless of method.
        network_id = request.query.get("network_id")

        # 2) POST body: JSON or form-urlencoded.
        if request.method == "POST" and not network_id:
            ctype = (request.headers.get("Content-Type") or "").lower()
            try:
                if "application/json" in ctype:
                    body = await request.json()
                    network_id = body.get("network_id")
                elif "application/x-www-form-urlencoded" in ctype:
                    form = await request.post()
                    network_id = form.get("network_id")
                else:
                    # Best-effort: try JSON first, fall back to raw text.
                    raw = await request.text()
                    if raw.strip().startswith("{"):
                        import json as _json
                        try:
                            network_id = _json.loads(raw).get("network_id")
                        except Exception:
                            pass
            except Exception:
                pass

        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            zerotier_network_action,
            action,
            network_id,
        )
        ctx.audit({"type": "zerotier_network", "action": action, "ok": result.get("ok")})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_tunnels_status(request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            functools.partial(
                tunnels_status,
                sys_funnel_status_sync=ctx.sys_funnel_status_sync,
                cloudflared_status_sync=ctx.cloudflared_status_sync,
                zerotier_status_sync=ctx.zerotier_status_sync,
            ),
        )
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_tunnels_active(request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            functools.partial(
                tunnels_active,
                sys_funnel_status_sync=ctx.sys_funnel_status_sync,
                cloudflared_status_sync=ctx.cloudflared_status_sync,
                zerotier_status_sync=ctx.zerotier_status_sync,
            ),
        )
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_tunnels_start(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]
        port = cfg.get("port", 8765)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            functools.partial(
                tunnels_start,
                port=port,
                tailscale_funnel_action_sync=ctx.tailscale_funnel_action_sync,
                cloudflared_funnel_action_sync=ctx.cloudflared_funnel_action_sync,
                sys_funnel_status_sync=ctx.sys_funnel_status_sync,
                cloudflared_status_sync=ctx.cloudflared_status_sync,
                zerotier_status_sync=ctx.zerotier_status_sync,
            ),
        )
        ctx.audit({"type": "tunnels_start", "active": (result.get("active") or {}).get("provider")})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_tunnels_stop(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]
        port = cfg.get("port", 8765)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            ctx.executor,
            functools.partial(
                tunnels_stop,
                port=port,
                tailscale_funnel_action_sync=ctx.tailscale_funnel_action_sync,
                cloudflared_funnel_action_sync=ctx.cloudflared_funnel_action_sync,
            ),
        )
        ctx.audit({"type": "tunnels_stop"})
        return ctx.cors_json_response(result)

    # v3.85.0: auto-update handlers live in a sibling module to keep
    # this file small.
    from arena.admin.handlers_update import make_update_handlers
    _upd = make_update_handlers(ctx)

    return AdminHandlers(
        sys_funnel=handle_v1_sys_funnel,
        token_regenerate=handle_v1_token_regenerate,
        tailscale_funnel=handle_v1_tailscale_funnel,
        cloudflared_tunnel=handle_v1_cloudflared_tunnel,
        zerotier_status=handle_v1_zerotier_status,
        zerotier_network=handle_v1_zerotier_network,
        tunnels_status=handle_v1_tunnels_status,
        tunnels_active=handle_v1_tunnels_active,
        tunnels_start=handle_v1_tunnels_start,
        tunnels_stop=handle_v1_tunnels_stop,
        update_status=_upd["update_status"],
        update_check=_upd["update_check"],
        update_apply=_upd["update_apply"],
        update_restart=_upd["update_restart"],
    )
