"""Handlers for lightweight resource listing and mission-management endpoints."""
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
    mission_templates: object
    mission_compose: object
    mission_create: object
    mission_run: object
    subagents_spawn: object



def make_resource_handlers(ctx: ResourceHandlerContext) -> ResourceHandlers:
    def _simple(sync_fn):
        async def handler(request: web.Request) -> web.Response:
            r = ctx.require_auth(request)
            if r:
                return r
            ctx.record_request()
            try:
                loop = asyncio.get_running_loop()
                return ctx.cors_json_response(await loop.run_in_executor(ctx.executor, sync_fn))
            except Exception as e:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)
        return handler

    async def handle_v1_missions(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            loop = asyncio.get_running_loop()
            missions = await loop.run_in_executor(ctx.executor, ctx.list_missions_sync)
            return ctx.cors_json_response({"ok": True, "count": len(missions), "missions": missions})
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_reports(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            loop = asyncio.get_running_loop()
            reports = await loop.run_in_executor(ctx.executor, ctx.list_reports_sync)
            return ctx.cors_json_response({"ok": True, "count": len(reports), "reports": reports})
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_mission_show(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        name = parse_qs(request.query_string).get("name", [""])[0]
        if not name:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing name parameter"}, status=400)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.mission_show_sync, name)
        return ctx.cors_json_response(result, status=200 if result.get("ok") else 404)

    async def _post_json(sync_fn, request: web.Request) -> web.Response:
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
        result = await loop.run_in_executor(ctx.executor, sync_fn, data)
        status = int(result.pop("status", 200 if result.get("ok") else 400))
        return ctx.cors_json_response(result, status=status)

    async def handle_v1_mission_compose(request: web.Request) -> web.Response:
        return await _post_json(ctx.mission_compose_sync, request)

    async def handle_v1_mission_create(request: web.Request) -> web.Response:
        result = await _post_json(ctx.mission_create_sync, request)
        return result

    async def handle_v1_mission_run(request: web.Request) -> web.Response:
        response = await _post_json(ctx.mission_run_sync, request)
        return response

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
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.subagent_spawn_sync, data)
        ctx.audit({"type": "subagent_spawn", "cmd": cmd, "name": data.get("name", ""), "ok": result.get("ok", False)})
        return ctx.cors_json_response(result)

    return ResourceHandlers(missions=handle_v1_missions, reports=handle_v1_reports, hooks=_simple(ctx.hooks_list_sync), agents=_simple(ctx.agents_list_sync), subagents=_simple(ctx.subagents_list_sync), mission_show=handle_v1_mission_show, mission_templates=_simple(ctx.mission_templates_sync), mission_compose=handle_v1_mission_compose, mission_create=handle_v1_mission_create, mission_run=handle_v1_mission_run, subagents_spawn=handle_v1_subagents_spawn)
