"""Handlers for lightweight resource listing and mission-management endpoints."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs

from aiohttp import web

from arena.handler_context import ResourceHandlerContext
from arena.handler_helpers import authed


@dataclass(frozen=True)
class ResourceHandlers:
    missions: Callable[..., Any]
    reports: Callable[..., Any]
    hooks: Callable[..., Any]
    agents: Callable[..., Any]
    subagents: Callable[..., Any]
    mission_show: Callable[..., Any]
    mission_status: Callable[..., Any]
    mission_report: Callable[..., Any]
    mission_history: Callable[..., Any]
    mission_lineage: Callable[..., Any]
    mission_catalog: Callable[..., Any]
    mission_templates: Callable[..., Any]
    mission_compose: Callable[..., Any]
    mission_propose: Callable[..., Any]
    mission_create: Callable[..., Any]
    mission_run: Callable[..., Any]
    mission_rerun: Callable[..., Any]
    mission_recover: Callable[..., Any]
    mission_followup: Callable[..., Any]
    mission_iterate: Callable[..., Any]
    subagents_spawn: Callable[..., Any]
    code_run_info: Callable[..., Any]
    code_artifact_download: Callable[..., Any]


def _query_bool(value: str) -> bool | None:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return None



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

    @authed(ctx)
    async def handle_v1_missions(request: web.Request) -> web.Response:
        try:
            loop = asyncio.get_running_loop()
            missions = await loop.run_in_executor(ctx.executor, ctx.list_missions_sync)
            return ctx.cors_json_response({"ok": True, "count": len(missions), "missions": missions})
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    @authed(ctx)
    async def handle_v1_reports(request: web.Request) -> web.Response:
        try:
            loop = asyncio.get_running_loop()
            reports = await loop.run_in_executor(ctx.executor, ctx.list_reports_sync)
            return ctx.cors_json_response({"ok": True, "count": len(reports), "reports": reports})
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    def _missing_name_error(hint_endpoint: str) -> dict:
        # v4.50.12: shared actionable-error payload for mission
        # endpoints that need a mission name. The MCP tool schemas
        # allow either `name` or `mission_id`; we surface both.
        return {
            "ok": False,
            "error": "missing required parameter 'name' (or 'mission_id')",
            "hint": "Pass the mission's saved name (case-sensitive). Call mission.catalog first to discover available mission names.",
            "required": ["name"],
            "endpoint": hint_endpoint,
        }

    @authed(ctx)
    async def handle_v1_mission_show(request: web.Request) -> web.Response:
        name = parse_qs(request.query_string).get("name", [""])[0]
        if not name:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response(
                _missing_name_error("GET /v1/mission/show?name=<mission-name>"),
                status=400,
            )
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.mission_show_sync, name)
        return ctx.cors_json_response(result, status=200 if result.get("ok") else 404)

    async def _mission_get(sync_fn, request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        name = parse_qs(request.query_string).get("name", [""])[0]
        if not name:
            ctx.record_request(is_error=True, count_request=False)
            # v4.50.12: use the request path in the hint so the model
            # sees the exact endpoint it just hit.
            return ctx.cors_json_response(
                _missing_name_error(f"GET {request.path}?name=<mission-name>"),
                status=400,
            )
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, sync_fn, name)
        return ctx.cors_json_response(result, status=200 if result.get("ok") else int(result.get("status", 404)))

    @authed(ctx)
    async def handle_v1_mission_catalog(request: web.Request) -> web.Response:
        query = parse_qs(request.query_string)
        payload = {
            "state": query.get("state", [""])[0],
            "template": query.get("template", [""])[0],
            "query": query.get("q", [""])[0],
            "limit": int(query.get("limit", [50])[0] or 50),
            "offset": int(query.get("offset", [0])[0] or 0),
        }
        has_report = _query_bool(query.get("has_report", [""])[0])
        if has_report is not None:
            payload["has_report"] = has_report
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.mission_catalog_sync, payload)
        return ctx.cors_json_response(result, status=200 if result.get("ok") else int(result.get("status", 400)))

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

    async def handle_v1_mission_propose(request: web.Request) -> web.Response:
        return await _post_json(ctx.mission_propose_sync, request)

    async def handle_v1_mission_create(request: web.Request) -> web.Response:
        result = await _post_json(ctx.mission_create_sync, request)
        return result

    async def handle_v1_mission_run(request: web.Request) -> web.Response:
        response = await _post_json(ctx.mission_run_sync, request)
        return response

    async def handle_v1_mission_rerun(request: web.Request) -> web.Response:
        response = await _post_json(ctx.mission_rerun_sync, request)
        return response

    async def handle_v1_mission_recover(request: web.Request) -> web.Response:
        response = await _post_json(ctx.mission_recover_sync, request)
        return response

    async def handle_v1_mission_followup(request: web.Request) -> web.Response:
        return await _post_json(ctx.mission_followup_sync, request)

    async def handle_v1_mission_iterate(request: web.Request) -> web.Response:
        return await _post_json(ctx.mission_iterate_sync, request)

    @authed(ctx)
    async def handle_v1_subagents_spawn(request: web.Request) -> web.Response:
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



    @authed(ctx)
    async def handle_v1_code_run_info(request: web.Request) -> web.Response:
        from arena.workbench.artifacts import run_info
        run_id = request.match_info.get("run_id", "")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, run_info, run_id)
        return ctx.cors_json_response(result, status=200 if result.get("ok") else 404)

    @authed(ctx)
    async def handle_v1_code_artifact_download(request: web.Request) -> web.StreamResponse:
        from arena.workbench.artifacts import runs_root, safe_rel, safe_run_id
        run_id = safe_run_id(request.match_info.get("run_id", ""))
        rel = safe_rel(request.match_info.get("path", ""))
        fp = runs_root() / run_id / "artifacts" / rel
        if not fp.is_file():
            return ctx.cors_json_response({"ok": False, "error": "artifact not found"}, status=404)
        return web.FileResponse(fp)

    return ResourceHandlers(missions=handle_v1_missions, reports=handle_v1_reports, hooks=_simple(ctx.hooks_list_sync), agents=_simple(ctx.agents_list_sync), subagents=_simple(ctx.subagents_list_sync), mission_show=handle_v1_mission_show, mission_status=lambda request: _mission_get(ctx.mission_status_sync, request), mission_report=lambda request: _mission_get(ctx.mission_report_sync, request), mission_history=lambda request: _mission_get(ctx.mission_history_sync, request), mission_lineage=lambda request: _mission_get(ctx.mission_lineage_sync, request), mission_catalog=handle_v1_mission_catalog, mission_templates=_simple(ctx.mission_templates_sync), mission_compose=handle_v1_mission_compose, mission_propose=handle_v1_mission_propose, mission_create=handle_v1_mission_create, mission_run=handle_v1_mission_run, mission_rerun=handle_v1_mission_rerun, mission_recover=handle_v1_mission_recover, mission_followup=handle_v1_mission_followup, mission_iterate=handle_v1_mission_iterate, subagents_spawn=handle_v1_subagents_spawn, code_run_info=handle_v1_code_run_info, code_artifact_download=handle_v1_code_artifact_download)

