"""Handlers for lightweight resource listing endpoints."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import parse_qs

from aiohttp import web

from arena.handler_context import ResourceHandlerContext


@dataclass(frozen=True)
class ResourceHandlers:
    missions: object
    reports: object
    hooks: object
    agents: object
    subagents: object
    mission_show: object
    subagents_spawn: object


def make_resource_handlers(ctx: ResourceHandlerContext) -> ResourceHandlers:
    async def handle_v1_missions(request: web.Request) -> web.Response:
        try:
            r = ctx.require_auth(request)
            if r:
                return r
            ctx.record_request()
            loop = asyncio.get_running_loop()
            missions = await loop.run_in_executor(ctx.executor, ctx.list_missions_sync)
            return ctx.cors_json_response({"ok": True, "count": len(missions), "missions": missions})
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_reports(request: web.Request) -> web.Response:
        try:
            r = ctx.require_auth(request)
            if r:
                return r
            ctx.record_request()
            loop = asyncio.get_running_loop()
            reports = await loop.run_in_executor(ctx.executor, ctx.list_reports_sync)
            return ctx.cors_json_response({"ok": True, "count": len(reports), "reports": reports})
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    def make_simple_handler(sync_fn, result_key: str):
        async def handler(request: web.Request) -> web.Response:
            r = ctx.require_auth(request)
            if r:
                return r
            ctx.record_request()
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(ctx.executor, sync_fn)
                return ctx.cors_json_response(result)
            except Exception as e:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)
        return handler

    async def handle_v1_mission_show(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        qs = parse_qs(request.query_string)
        name = qs.get("name", [""])[0]
        if not name:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing name parameter"}, status=400)
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(ctx.executor, ctx.mission_show_sync, name)
            if not result.get("ok"):
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response(result, status=404)
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


    async def handle_v1_subagents_spawn(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            data = await request.json()
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        cmd = data.get("cmd", "")
        if not cmd:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing cmd"}, status=400)
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(ctx.executor, ctx.subagent_spawn_sync, data)
            ctx.audit({"type": "subagent_spawn", "cmd": cmd, "name": data.get("name", ""), "ok": result.get("ok", False)})
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)
    return ResourceHandlers(
        missions=handle_v1_missions,
        reports=handle_v1_reports,
        hooks=make_simple_handler(ctx.hooks_list_sync, "hooks"),
        agents=make_simple_handler(ctx.agents_list_sync, "agents"),
        subagents=make_simple_handler(ctx.subagents_list_sync, "subagents"),
        mission_show=handle_v1_mission_show,
        subagents_spawn=handle_v1_subagents_spawn,
    )
