"""Handlers for the built-in planner endpoint."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from arena.cognitive_input import (
    CognitiveInputError,
    optional_string_list,
    optional_text,
    positive_int,
    reject_unknown,
    required_text,
)
from arena.handler_context import PlannerHandlerContext
from arena.handler_helpers import authed, json_object_body


@dataclass(frozen=True)
class PlannerHandlers:
    plan: Callable[..., Any]



def make_planner_handlers(ctx: PlannerHandlerContext) -> PlannerHandlers:
    @authed(ctx)
    async def handle_v1_plan(request: web.Request) -> web.Response:
        data = await json_object_body(request)
        try:
            reject_unknown(data, frozenset({
                "goal", "context", "constraints", "max_steps", "memory_profile",
            }))
            goal = required_text(data, "goal")
            context = optional_text(data, "context")
            constraints = optional_string_list(data, "constraints")
            max_steps = positive_int(data, "max_steps", 8)
            memory_profile = optional_text(data, "memory_profile") or None
            result = ctx.build_plan(
                goal=goal, context=context, constraints=constraints,
                max_steps=max_steps, memory_profile=memory_profile,
            )
        except CognitiveInputError as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)
        ctx.audit({"event": "plan_created", "goal": goal, "profile": result.get("suggested_memory_profile"), "steps": len(result.get("steps") or [])})
        return ctx.cors_json_response(result)

    return PlannerHandlers(plan=handle_v1_plan)
