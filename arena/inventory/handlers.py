"""Handlers for inventory/hardware endpoints."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import HandlerContext


@dataclass(frozen=True)
class HardwareHandlers:
    inventory: object
    hardware: object
    hwinfo: object


def make_hardware_handlers(ctx: HandlerContext) -> HardwareHandlers:
    async def handle_v1_inventory(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        section = request.query.get("section")
        fmt = (request.query.get("format") or "text").lower()
        if fmt not in ("text", "json"):
            return ctx.cors_json_response({"ok": False, "error": "format must be 'text' or 'json'"}, status=400)
        try:
            timeout = int(request.query.get("timeout", "30"))
            timeout = min(max(5, timeout), 120)
        except Exception:
            timeout = 30
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(ctx.executor, ctx.inventory_sync, section, fmt, timeout)
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_hardware(request: web.Request) -> web.Response:
        """GET /v1/hardware — Canonical rich hardware/system inventory."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            timeout = int(request.query.get("timeout", "45"))
            timeout = min(max(10, timeout), 120)
        except Exception:
            timeout = 45
        include_inventory = (request.query.get("include_inventory", "1").lower() not in ("0", "false", "no"))
        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(ctx.slow_executor, ctx.hardware_sync, timeout),
                timeout=float(timeout) + 5.0,
            )
            if not include_inventory:
                result.pop("inventory", None)
            return ctx.cors_json_response(result)
        except asyncio.TimeoutError:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"hardware collection timed out ({timeout}s)"}, status=504)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_hwinfo(request: web.Request) -> web.Response:
        """GET /v1/hwinfo — Backwards-compatible alias for /v1/hardware."""
        return await handle_v1_hardware(request)

    return HardwareHandlers(
        inventory=handle_v1_inventory,
        hardware=handle_v1_hardware,
        hwinfo=handle_v1_hwinfo,
    )
