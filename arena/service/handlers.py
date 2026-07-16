"""Handlers for service/status/capabilities/restart endpoints."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from aiohttp import web
from arena.app_keys import APP_CFG

from arena.handler_context import ServiceHandlerContext
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class ServiceHandlers:
    service_info: object
    sys_svc: object
    capabilities: object
    restart: object


def make_service_handlers(ctx: ServiceHandlerContext) -> ServiceHandlers:
    @authed(ctx)
    async def handle_v1_service_info(request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        info = await loop.run_in_executor(ctx.executor, ctx.service_info_sync)
        return ctx.cors_json_response(info)

    async def handle_v1_sys_svc(request: web.Request) -> web.Response:
        """GET /v1/sys/svc — Service status."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.sys_svc_sync)
        return ctx.cors_json_response(result)

    async def handle_v1_capabilities(request: web.Request) -> web.Response:
        """GET /v1/capabilities — Agent-facing capability map."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.capabilities_sync)
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_restart(request: web.Request) -> web.Response:
        cfg = request.app[APP_CFG]
        port = int(cfg.get("port", 8765))
        ctx.audit({"type": "restart_requested"})

        # Spawn the respawn helper BEFORE we die.
        spawned, method = ctx.spawn_respawn_helper(port)

        # Schedule shutdown after the response is sent.
        async def _exit_soon():
            await asyncio.sleep(1.5)
            os._exit(0)

        asyncio.create_task(_exit_soon())

        return ctx.cors_json_response({
            "ok": True,
            "respawn_scheduled": spawned,
            "method": method,
            "shutdown_in_seconds": 1.5,
            "note": ("Bridge shuts down in 1.5s. A detached helper will re-launch it ~3-5s later."
                     if spawned else "WARNING: respawn helper failed to spawn — manual restart required."),
            "manual_restart_hint": (
                "Windows: schtasks /Run /tn ArenaUnifiedBridge | "
                "Linux: systemctl --user restart arena-bridge | "
                "macOS: launchctl kickstart -k gui/$UID/com.arena.bridge"
            ),
        })

    return ServiceHandlers(
        service_info=handle_v1_service_info,
        sys_svc=handle_v1_sys_svc,
        capabilities=handle_v1_capabilities,
        restart=handle_v1_restart,
    )
