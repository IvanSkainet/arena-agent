"""Handlers for bounded ReAct loops and reflection."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from arena.cognitive_input import (
    CognitiveInputError,
    optional_object,
    optional_string_list,
    optional_text,
    positive_int,
    reject_unknown,
    required_text,
)
from arena.handler_context import AgenticHandlerContext
from arena.handler_helpers import authed, json_object_body


@dataclass(frozen=True)
class AgenticHandlers:
    react: Callable[..., Any]
    reflect: Callable[..., Any]



def make_agentic_handlers(ctx: AgenticHandlerContext) -> AgenticHandlers:
    @authed(ctx)
    async def handle_v1_react(request: web.Request) -> web.Response:
        data = await json_object_body(request)
        try:
            reject_unknown(data, frozenset({
                "goal", "context", "constraints", "max_iterations",
                "memory_profile", "url",
            }))
            goal = required_text(data, "goal")
            result = ctx.react_sync(
                goal=goal,
                context=optional_text(data, "context"),
                constraints=optional_string_list(data, "constraints"),
                max_iterations=positive_int(data, "max_iterations", 4),
                memory_profile=optional_text(data, "memory_profile") or None,
                url=optional_text(data, "url"),
            )
        except CognitiveInputError as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)
        ctx.audit({"event": "react_run", "goal": goal, "iterations": len(result.get("iterations") or []), "profile": result.get("memory_profile")})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_reflect(request: web.Request) -> web.Response:
        data = await json_object_body(request)
        try:
            reject_unknown(data, frozenset({"goal", "run", "notes", "outcome"}))
            goal = required_text(data, "goal")
            result = ctx.reflect_sync(
                goal=goal,
                run=optional_object(data, "run"),
                notes=optional_text(data, "notes"),
                outcome=optional_text(data, "outcome"),
            )
        except CognitiveInputError as e:
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)
        ctx.audit({"event": "reflect_run", "goal": result.get("goal", ""), "confidence": result.get("confidence", "")})
        return ctx.cors_json_response(result)

    return AgenticHandlers(react=handle_v1_react, reflect=handle_v1_reflect)
