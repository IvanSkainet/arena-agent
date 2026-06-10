"""Handlers for service/status/capabilities/restart endpoints."""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import ServiceHandlerContext


@dataclass(frozen=True)
class ServiceHandlers:
    service_info: object
    sys_svc: object
    capabilities: object
    restart: object


def make_service_handlers(ctx: ServiceHandlerContext) -> ServiceHandlers:
    async def handle_v1_service_info(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(ctx.executor, ctx.service_info_sync)
            return ctx.cors_json_response(info)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_sys_svc(request: web.Request) -> web.Response:
        """GET /v1/sys/svc — Service status."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(ctx.executor, ctx.sys_svc_sync)
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_capabilities(request: web.Request) -> web.Response:
        """GET /v1/capabilities — Agent-facing capability map."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(ctx.executor, ctx.capabilities_sync)
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_restart(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        cfg = request.app["cfg"]
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
