"""HTTP Handlers for Book of Eternity (BoE) game relay and agent endpoints."""
from __future__ import annotations

import asyncio
import functools
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aiohttp import web

from arena.game import boe_relay
from arena.handler_helpers import authed, err_json, ok_json, safe_float


@dataclass(frozen=True)
class BoeHandlers:
    boe_status: Callable[..., Any]
    boe_wait_inbox: Callable[..., Any]
    boe_read_turn: Callable[..., Any]
    boe_write_json: Callable[..., Any]
    boe_complete_turn: Callable[..., Any]
    boe_fail_turn: Callable[..., Any]
    boe_repair_turn: Callable[..., Any]

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def keys(self) -> list[str]:
        return [
            "boe_status",
            "boe_wait_inbox",
            "boe_read_turn",
            "boe_write_json",
            "boe_complete_turn",
            "boe_fail_turn",
            "boe_repair_turn",
        ]


def _resolve_session_dir(body: dict[str, Any], query: Any) -> Path:
    """Resolve session directory from request body, query or fallback."""
    raw = (body.get("session_dir") or query.get("session_dir") or "game_session")
    return Path(str(raw))


def make_boe_handlers(ctx: Any) -> BoeHandlers:
    """Return dictionary-like BoeHandlers dataclass keyed by route identifier."""

    @authed(ctx)
    async def handle_boe_status(request: web.Request) -> web.Response:
        """GET /v1/game/boe/status -- inspect current session & inbox state."""
        session_dir = _resolve_session_dir({}, request.query)
        loop = asyncio.get_running_loop()
        res = await loop.run_in_executor(ctx.executor, boe_relay.get_status, session_dir)
        return ctx.cors_json_response(res)

    @authed(ctx)
    async def handle_boe_wait_inbox(request: web.Request) -> web.Response:
        """POST /v1/game/boe/wait_inbox -- long-poll for pending turn packet."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}

        session_dir = _resolve_session_dir(body, request.query)
        timeout = safe_float(body.get("timeout_sec", 25.0), default=25.0, minimum=0.5, maximum=120.0)

        loop = asyncio.get_running_loop()
        packet = await loop.run_in_executor(
            ctx.executor, functools.partial(boe_relay.wait_for_inbox, session_dir, timeout)
        )

        if packet:
            ctx.audit({
                "type": "game.boe.inbox_received",
                "turnNumber": packet.get("turnNumber"),
                "requestId": packet.get("requestId"),
                "kind": packet.get("kind"),
            })
            return ok_json(ctx, {"has_packet": True, "packet": packet})

        return ok_json(ctx, {"has_packet": False, "packet": None, "hint": "No pending turn within timeout"})

    @authed(ctx)
    async def handle_boe_read_turn(request: web.Request) -> web.Response:
        """GET /v1/game/boe/read_turn -- read current turn request & state."""
        session_dir = _resolve_session_dir({}, request.query)
        loop = asyncio.get_running_loop()
        status_info = await loop.run_in_executor(ctx.executor, boe_relay.get_status, session_dir)
        inbox = status_info.get("inbox")
        return ok_json(ctx, {"status": status_info, "inbox": inbox})

    @authed(ctx)
    async def handle_boe_write_json(request: web.Request) -> web.Response:
        """POST /v1/game/boe/write_json -- safe atomic write of session state JSON."""
        try:
            body = await request.json()
        except Exception:
            return err_json(ctx, "JSON body required", status=400)
        if not isinstance(body, dict):
            return err_json(ctx, "JSON object required", status=400)

        rel_path = str(body.get("path") or "").strip()
        if not rel_path:
            return err_json(ctx, "path required", status=400)

        if "data" not in body:
            return err_json(ctx, "data required", status=400)

        session_dir = _resolve_session_dir(body, request.query)

        try:
            loop = asyncio.get_running_loop()
            written = await loop.run_in_executor(
                ctx.executor,
                functools.partial(
                    boe_relay.safe_write_json,
                    session_dir,
                    rel_path,
                    body["data"],
                    current_realm=body.get("current_realm") or request.query.get("current_realm"),
                ),
            )
            ctx.audit({
                "type": "game.boe.write_json",
                "path": rel_path,
                "session_dir": str(session_dir),
            })
            return ok_json(ctx, {"path": str(written), "written": True})
        except PermissionError as pe:
            return err_json(ctx, str(pe), status=403)
        except Exception as e:
            return err_json(ctx, f"Write failed: {e}", status=500)

    @authed(ctx)
    async def handle_boe_complete_turn(request: web.Request) -> web.Response:
        """POST /v1/game/boe/complete_turn -- complete the active turn."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}

        session_dir = _resolve_session_dir(body, request.query)
        loop = asyncio.get_running_loop()

        fn = functools.partial(
            boe_relay.complete_turn,
            session_dir,
            session_id=body.get("session_id"),
            request_id=body.get("request_id"),
            turn_number=body.get("turn_number"),
            files_modified=body.get("files_modified") or body.get("filesModified"),
            summary=str(body.get("summary") or "Turn completed"),
            state_updates=body.get("state_updates"),
        )
        res = await loop.run_in_executor(ctx.executor, fn)
        ctx.audit({
            "type": "game.boe.complete_turn",
            "turnNumber": res.get("turnNumber"),
            "requestId": res.get("requestId"),
        })
        return ok_json(ctx, {"result": res})

    @authed(ctx)
    async def handle_boe_fail_turn(request: web.Request) -> web.Response:
        """POST /v1/game/boe/fail_turn -- report a turn error."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}

        error_message = str(body.get("error") or "Unknown game master error").strip()
        session_dir = _resolve_session_dir(body, request.query)
        loop = asyncio.get_running_loop()

        fn = functools.partial(
            boe_relay.fail_turn,
            session_dir,
            error_message=error_message,
            session_id=body.get("session_id"),
            request_id=body.get("request_id"),
            turn_number=body.get("turn_number"),
        )
        res = await loop.run_in_executor(ctx.executor, fn)
        ctx.audit({
            "type": "game.boe.fail_turn",
            "turnNumber": res.get("turnNumber"),
            "error": error_message,
        })
        return ok_json(ctx, {"result": res})

    @authed(ctx)
    async def handle_boe_repair_turn(request: web.Request) -> web.Response:
        """POST /v1/game/boe/repair_turn -- complete validation repair handshake."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        if not isinstance(body, dict):
            body = {}

        session_dir = _resolve_session_dir(body, request.query)
        loop = asyncio.get_running_loop()

        fn = functools.partial(
            boe_relay.repair_ready,
            session_dir,
            repair_summary=str(body.get("summary") or "Validation repair applied"),
            session_id=body.get("session_id"),
            request_id=body.get("request_id"),
        )
        res = await loop.run_in_executor(ctx.executor, fn)
        ctx.audit({
            "type": "game.boe.repair_turn",
            "requestId": res.get("requestId"),
        })
        return ok_json(ctx, {"result": res})

    return BoeHandlers(
        boe_status=handle_boe_status,
        boe_wait_inbox=handle_boe_wait_inbox,
        boe_read_turn=handle_boe_read_turn,
        boe_write_json=handle_boe_write_json,
        boe_complete_turn=handle_boe_complete_turn,
        boe_fail_turn=handle_boe_fail_turn,
        boe_repair_turn=handle_boe_repair_turn,
    )
