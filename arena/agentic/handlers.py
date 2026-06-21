"""Handlers for bounded ReAct loops and reflection."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import AgenticHandlerContext


@dataclass(frozen=True)
class AgenticHandlers:
    react: object
    reflect: object



def make_agentic_handlers(ctx: AgenticHandlerContext) -> AgenticHandlers:
    async def handle_v1_react(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            data = await request.json()
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        goal = str(data.get("goal", "")).strip()
        if not goal:
            return ctx.cors_json_response({"ok": False, "error": "missing goal"}, status=400)
        result = ctx.react_sync(
            goal=goal,
            context=str(data.get("context", "") or ""),
            constraints=data.get("constraints") or [],
            max_iterations=int(data.get("max_iterations", 4) or 4),
            memory_profile=data.get("memory_profile"),
            url=str(data.get("url", "") or ""),
        )
        ctx.audit({"event": "react_run", "goal": goal, "iterations": len(result.get("iterations") or []), "profile": result.get("memory_profile")})
        return ctx.cors_json_response(result)

    async def handle_v1_reflect(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            data = await request.json()
        except Exception as e:
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        result = ctx.reflect_sync(
            goal=str(data.get("goal", "") or ""),
            run=data.get("run") or {},
            notes=str(data.get("notes", "") or ""),
            outcome=str(data.get("outcome", "") or ""),
        )
        ctx.audit({"event": "reflect_run", "goal": result.get("goal", ""), "confidence": result.get("confidence", "")})
        return ctx.cors_json_response(result)

    return AgenticHandlers(react=handle_v1_react, reflect=handle_v1_reflect)
