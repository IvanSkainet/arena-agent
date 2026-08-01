"""Handlers for desktop control-lease endpoints."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.autonomy import set_yolo as _set_yolo, yolo_status as _yolo_status
from arena.handler_context import ControlLeaseHandlerContext
from arena.handler_helpers import authed


@dataclass(frozen=True)
class ControlLeaseHandlers:
    status: object
    pause: object
    resume: object
    revoke: object
    halt: object
    unhalt: object
    yolo_get: object
    yolo_set: object


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
        # v4.97.0: full agent stop (kill-switch). .get() keeps older state
        # dicts (e.g. unit-test fixtures) working.
        "agent_halted": state.get("agent_halted", False),
        "halted_at": state.get("halted_at"),
        "halted_reason": state.get("halted_reason"),
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

    @authed(ctx)
    async def handle_v1_control_halt(request: web.Request) -> web.Response:
        """v4.97.0: engage the FULL agent stop (kill-switch). Blocks every
        non-read-only agent action across all entry points. The desktop lease
        (pause/revoke) is left untouched; this is the bigger red button."""
        reason = None
        try:
            body = await request.json()
            reason = body.get("reason")
        except Exception:
            pass
        with ctx.control_lock:
            ctx.control_state["agent_halted"] = True
            ctx.control_state["halted_at"] = ctx.utc_now()
            ctx.control_state["halted_reason"] = reason or "User halted the agent"
            halted_at = ctx.control_state["halted_at"]
            halted_reason = ctx.control_state["halted_reason"]
        ctx.log_warning("[Control] Agent HALTED (full stop; reason: %s)", reason)
        return ctx.cors_json_response({
            "ok": True, "agent_halted": True,
            "halted_at": halted_at, "reason": halted_reason,
        })

    @authed(ctx)
    async def handle_v1_control_unhalt(request: web.Request) -> web.Response:
        """v4.97.0: disengage the full agent stop."""
        with ctx.control_lock:
            was = ctx.control_state.get("agent_halted", False)
            ctx.control_state["agent_halted"] = False
            ctx.control_state["halted_at"] = None
            ctx.control_state["halted_reason"] = None
        ctx.log_info("[Control] Agent UNHALTED (was halted: %s)", was)
        return ctx.cors_json_response({"ok": True, "agent_halted": False, "was_halted": was})

    @authed(ctx)
    async def handle_v1_control_yolo_get(request: web.Request) -> web.Response:
        """v4.97.0: read YOLO (auto-approve) state + the ack token the UI needs."""
        return ctx.cors_json_response(_yolo_status())

    @authed(ctx)
    async def handle_v1_control_yolo_set(request: web.Request) -> web.Response:
        """v4.97.0: engage/disengage YOLO. Enabling requires the ack token."""
        body = {}
        try:
            body = await request.json() or {}
        except Exception:
            body = {}
        enabled = body.get("enabled", False)
        # accept bool or stringy truthy from a checkbox-style form
        if isinstance(enabled, str):
            enabled = enabled.strip().lower() in ("1", "true", "yes", "on")
        res = _set_yolo(bool(enabled), ack=body.get("ack"),
                        by=body.get("by") or "dashboard")
        if not res.get("ok"):
            ctx.log_warning("[Control] YOLO enable REFUSED: %s", res.get("error"))
            return ctx.cors_json_response(res, status=400)
        ctx.log_warning("[Control] YOLO %s (by %s)",
                        "ENABLED" if res.get("yolo") else "disabled",
                        body.get("by") or "dashboard")
        return ctx.cors_json_response(res)

    return ControlLeaseHandlers(
        status=handle_v1_control_status,
        pause=handle_v1_control_pause,
        resume=handle_v1_control_resume,
        revoke=handle_v1_control_revoke,
        halt=handle_v1_control_halt,
        unhalt=handle_v1_control_unhalt,
        yolo_get=handle_v1_control_yolo_get,
        yolo_set=handle_v1_control_yolo_set,
    )
