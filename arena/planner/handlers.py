"""Handlers for the built-in planner endpoint."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import PlannerHandlerContext
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class PlannerHandlers:
    plan: object



def make_planner_handlers(ctx: PlannerHandlerContext) -> PlannerHandlers:
    @authed(ctx)
    async def handle_v1_plan(request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        goal = str(data.get("goal", "")).strip()
        if not goal:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing goal"}, status=400)
        try:
            result = ctx.build_plan(
                goal=goal,
                context=str(data.get("context", "") or ""),
                constraints=data.get("constraints") or [],
                max_steps=data.get("max_steps", 8),
                memory_profile=data.get("memory_profile"),
            )
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)
        ctx.audit({"event": "plan_created", "goal": goal, "profile": result.get("suggested_memory_profile"), "steps": len(result.get("steps") or [])})
        return ctx.cors_json_response(result)

    return PlannerHandlers(plan=handle_v1_plan)
