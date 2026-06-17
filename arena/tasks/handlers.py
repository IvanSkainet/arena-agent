"""Handlers for task queue endpoints."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import TaskHandlerContext


@dataclass(frozen=True)
class TaskHandlers:
    tasks_get: object
    tasks_post: object
    tasks_clean: object


def make_task_handlers(ctx: TaskHandlerContext) -> TaskHandlers:
    async def handle_v1_tasks_get(request: web.Request) -> web.Response:
        """GET /v1/tasks?status=inbox|running|done|failed&limit=20 — list tasks."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        status = request.query.get("status", "")
        try:
            limit = int(request.query.get("limit", "20"))
        except ValueError:
            limit = 20
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(ctx.executor, ctx.tasks_list_sync, status, limit)
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_v1_tasks_post(request: web.Request) -> web.Response:
        """POST /v1/tasks — Submit task. Body: {cmd, title?, description?, priority?, cwd?, timeout?, env?}."""
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
        title = data.get("title", "")
        if not cmd and not title:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing cmd or title"}, status=400)
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(ctx.executor, ctx.task_submit_sync, data)
            ctx.audit({"type": "task_submit", "task_id": result.get("task_id"), "cmd": cmd or title})
            return ctx.cors_json_response(result)
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Internal error"}, status=500)

    async def handle_v1_tasks_clean(request: web.Request) -> web.Response:
        """POST /v1/tasks/clean — Clean completed tasks older than 24h."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(ctx.executor, ctx.tasks_clean_sync)
            ctx.audit({"type": "tasks_clean", "removed": result.get("removed", 0)})
            return ctx.cors_json_response(result)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return TaskHandlers(
        tasks_get=handle_v1_tasks_get,
        tasks_post=handle_v1_tasks_post,
        tasks_clean=handle_v1_tasks_clean,
    )
