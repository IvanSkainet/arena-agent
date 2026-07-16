"""Handlers for inventory/hardware endpoints."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import HandlerContext
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class HardwareHandlers:
    inventory: object
    hardware: object
    hwinfo: object
    registry: object


def make_hardware_handlers(ctx: HandlerContext) -> HardwareHandlers:
    async def handle_v1_inventory_registry(request: web.Request) -> web.Response:
        """GET /v1/inventory/registry — machine-readable list of every
        inventory section: name, label, category, show_in_doctor.
        Used by the Dashboard to build the Full Inventory checkbox
        strip and Cards mapping without hand-maintaining a duplicate
        list in JS.
        """
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        from arena.inventory.registry import registry_meta
        return ctx.cors_json_response({"ok": True, "sections": registry_meta()})

    @authed(ctx)
    async def handle_v1_inventory(request: web.Request) -> web.Response:
        section = request.query.get("section")
        fmt = (request.query.get("format") or "text").lower()
        if fmt not in ("text", "json"):
            return ctx.cors_json_response({"ok": False, "error": "format must be 'text' or 'json'"}, status=400)
        try:
            timeout = int(request.query.get("timeout", "30"))
            timeout = min(max(5, timeout), 120)
        except Exception:
            timeout = 30
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.inventory_sync, section, fmt, timeout)
        return ctx.cors_json_response(result)

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
            loop = asyncio.get_running_loop()
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
        registry=handle_v1_inventory_registry,
    )
