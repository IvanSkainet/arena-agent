"""Handlers for desktop control-lease endpoints."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import ControlLeaseHandlerContext
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class ControlLeaseHandlers:
    status: object
    pause: object
    resume: object
    revoke: object


def _snapshot(state: dict) -> dict:
    return {
        "ok": True,
        "control": state["status"],
        "reason": state["reason"],
        "paused_at": state["paused_at"],
        "revoked_at": state["revoked_at"],
        "last_agent_input_at": state["last_agent_input_at"],
        "last_user_input_at": state["last_user_input_at"],
        "session_id": state["session_id"],
    }


def make_control_lease_handlers(ctx: ControlLeaseHandlerContext) -> ControlLeaseHandlers:
    @authed(ctx)
    async def handle_v1_control_status(request: web.Request) -> web.Response:
        with ctx.control_lock:
            return ctx.cors_json_response(_snapshot(ctx.control_state))

    @authed(ctx)
    async def handle_v1_control_pause(request: web.Request) -> web.Response:
        reason = None
        try:
            body = await request.json()
            reason = body.get("reason")
        except Exception:
            pass
        with ctx.control_lock:
            if ctx.control_state["status"] == "revoked":
                return ctx.cors_json_response({
                    "ok": False,
                    "error": "control_revoked",
                    "message": "Control is revoked. Use /v1/control/resume to re-activate.",
                }, status=409)
            ctx.control_state["status"] = "paused"
            ctx.control_state["reason"] = reason
            ctx.control_state["paused_at"] = ctx.utc_now()
            paused_at = ctx.control_state["paused_at"]
        ctx.log_info("[Control] Agent desktop control PAUSED (reason: %s)", reason)
        return ctx.cors_json_response({"ok": True, "control": "paused", "reason": reason, "paused_at": paused_at})

    @authed(ctx)
    async def handle_v1_control_resume(request: web.Request) -> web.Response:
        with ctx.control_lock:
            prev = ctx.control_state["status"]
            ctx.control_state["status"] = "active"
            ctx.control_state["reason"] = None
            ctx.control_state["paused_at"] = None
            ctx.control_state["revoked_at"] = None
            resumed_at = ctx.utc_now()
        ctx.log_info("[Control] Agent desktop control RESUMED (was: %s)", prev)
        return ctx.cors_json_response({"ok": True, "control": "active", "previous_status": prev, "resumed_at": resumed_at})

    @authed(ctx)
    async def handle_v1_control_revoke(request: web.Request) -> web.Response:
        reason = None
        try:
            body = await request.json()
            reason = body.get("reason")
        except Exception:
            pass
        with ctx.control_lock:
            ctx.control_state["status"] = "revoked"
            ctx.control_state["reason"] = reason or "User revoked control"
            ctx.control_state["revoked_at"] = ctx.utc_now()
            revoked_reason = ctx.control_state["reason"]
            revoked_at = ctx.control_state["revoked_at"]
        ctx.log_warning("[Control] Agent desktop control REVOKED (reason: %s)", reason)
        return ctx.cors_json_response({"ok": True, "control": "revoked", "reason": revoked_reason, "revoked_at": revoked_at})

    return ControlLeaseHandlers(
        status=handle_v1_control_status,
        pause=handle_v1_control_pause,
        resume=handle_v1_control_resume,
        revoke=handle_v1_control_revoke,
    )
