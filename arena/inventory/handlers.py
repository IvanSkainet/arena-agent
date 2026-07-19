"""Handlers for inventory/hardware endpoints."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import HandlerContext
from arena.handler_helpers import authed, err_json


# v4.50.2: cache the last successful /v1/hardware and /v1/inventory
# response for 60 s so a Windows dashboard-reload that pulls both
# endpoints in parallel doesn't re-run inventory.py twice at the price
# of two full WMI startups (~ 30 s each). Cache is process-local; a
# bridge restart flushes it. `nocache=1` query param on either
# endpoint forces a fresh collection.
_HW_CACHE_TTL_SEC = 60.0
_hw_cache: dict = {"at": 0.0, "result": None, "opts_key": None}
_inv_cache: dict = {"at": 0.0, "result": None, "opts_key": None}


def _cache_lookup(cache: dict, key, now_fn) -> object | None:
    if cache.get("opts_key") != key:
        return None
    if now_fn() - cache.get("at", 0.0) > _HW_CACHE_TTL_SEC:
        return None
    return cache.get("result")


def _cache_store(cache: dict, key, result, now_fn) -> None:
    cache["at"] = now_fn()
    cache["opts_key"] = key
    cache["result"] = result


@dataclass(frozen=True)
class HardwareHandlers:
    inventory: object
    hardware: object
    hwinfo: object
    registry: object


def make_hardware_handlers(ctx: HandlerContext) -> HardwareHandlers:
    @authed(ctx)
    async def handle_v1_inventory_registry(request: web.Request) -> web.Response:
        """GET /v1/inventory/registry — machine-readable list of every
        inventory section: name, label, category, show_in_doctor.
        Used by the Dashboard to build the Full Inventory checkbox
        strip and Cards mapping without hand-maintaining a duplicate
        list in JS.
        """
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
        nocache = (request.query.get("nocache", "0").lower() in ("1", "true", "yes"))
        key = (section or "", fmt, int(timeout))
        import time as _t
        if not nocache:
            cached = _cache_lookup(_inv_cache, key, _t.monotonic)
            if cached is not None:
                out = dict(cached)
                out["cache"] = {"hit": True, "age_sec": round(_t.monotonic() - _inv_cache["at"], 1)}
                return ctx.cors_json_response(out)
        result = await loop.run_in_executor(ctx.executor, ctx.inventory_sync, section, fmt, timeout)
        if isinstance(result, dict) and result.get("ok"):
            _cache_store(_inv_cache, key, result, _t.monotonic)
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_hardware(request: web.Request) -> web.Response:
        """GET /v1/hardware — Canonical rich hardware/system inventory."""
        try:
            timeout = int(request.query.get("timeout", "45"))
            timeout = min(max(10, timeout), 120)
        except Exception:
            timeout = 45
        include_inventory = (request.query.get("include_inventory", "1").lower() not in ("0", "false", "no"))
        nocache = (request.query.get("nocache", "0").lower() in ("1", "true", "yes"))
        key = (int(timeout), include_inventory)
        import time as _t
        if not nocache:
            cached = _cache_lookup(_hw_cache, key, _t.monotonic)
            if cached is not None:
                out = dict(cached)
                out["cache"] = {"hit": True, "age_sec": round(_t.monotonic() - _hw_cache["at"], 1)}
                return ctx.cors_json_response(out)
        try:
            loop = asyncio.get_running_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(ctx.slow_executor, ctx.hardware_sync, timeout),
                timeout=float(timeout) + 5.0,
            )
            if not include_inventory:
                result.pop("inventory", None)
            if isinstance(result, dict) and result.get("ok", True):
                _cache_store(_hw_cache, key, result, _t.monotonic)
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
