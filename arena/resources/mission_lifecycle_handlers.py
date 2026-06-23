"""Mission family and schedule handlers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import parse_qs

from aiohttp import web

from arena.handler_context import MissionLifecycleHandlerContext


@dataclass(frozen=True)
class MissionLifecycleHandlers:
    mission_family: object
    mission_schedules: object
    mission_schedules_tick: object



def _query_bool(value: str) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None



def make_mission_lifecycle_handlers(ctx: MissionLifecycleHandlerContext) -> MissionLifecycleHandlers:
    async def handle_v1_mission_family(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        name = parse_qs(request.query_string).get("name", [""])[0]
        if not name:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing name parameter"}, status=400)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.mission_family_sync, name)
        return ctx.cors_json_response(result, status=200 if result.get("ok") else int(result.get("status", 404)))

    async def handle_v1_mission_schedules(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        loop = asyncio.get_running_loop()
        if request.method == "GET":
            query = parse_qs(request.query_string)
            payload = {
                "action": query.get("action", [""])[0],
                "limit": int(query.get("limit", [100])[0] or 100),
                "due_only": _query_bool(query.get("due_only", [""])[0]) is True,
            }
            enabled = _query_bool(query.get("enabled", [""])[0])
            if enabled is not None:
                payload["enabled"] = enabled
            result = await loop.run_in_executor(ctx.executor, ctx.mission_schedules_sync, payload)
            return ctx.cors_json_response(result, status=200 if result.get("ok") else int(result.get("status", 400)))
        try:
            data = await request.json()
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        sync_fn = ctx.mission_schedule_save_sync if request.method == "POST" else ctx.mission_schedule_delete_sync
        result = await loop.run_in_executor(ctx.executor, sync_fn, data)
        status = int(result.pop("status", 200 if result.get("ok") else 400))
        return ctx.cors_json_response(result, status=status)

    async def handle_v1_mission_schedules_tick(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            data = await request.json()
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.mission_schedule_tick_sync, data)
        status = int(result.pop("status", 200 if result.get("ok") else 400))
        return ctx.cors_json_response(result, status=status)

    return MissionLifecycleHandlers(
        mission_family=handle_v1_mission_family,
        mission_schedules=handle_v1_mission_schedules,
        mission_schedules_tick=handle_v1_mission_schedules_tick,
    )


__all__ = ["MissionLifecycleHandlers", "make_mission_lifecycle_handlers"]
