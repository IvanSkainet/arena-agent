"""HTTP handlers for the v4.38.0 unified autostart endpoints.

Split out from ``arena/admin/handlers.py`` when that file
reached the 600-line runtime threshold. Kept in a sibling
module so ``handlers.py`` stays modular (same pattern the
v4.19.0 proposal handlers followed).

Exposes two handlers:

    GET  /v1/autostart              -- state_snapshot for every transport
    POST /v1/autostart/{transport}  -- toggle one transport
"""
from __future__ import annotations

from typing import Any

from aiohttp import web

from arena.app_keys import APP_CFG
from arena.handler_helpers import authed


def make_autostart_handlers(ctx: Any) -> dict:
    """Build the two v4.38.0 autostart handlers. ``ctx`` is
    an ``AdminHandlerContext`` -- we only use its ``root_agent``
    (for marker paths), ``cors_json_response`` (for wire
    responses) and ``audit`` (for the audit log)."""

    @authed(ctx)
    async def handle_v1_autostart_get(request: web.Request) -> web.Response:
        """GET /v1/autostart -- unified snapshot of every
        transport's autostart state. See
        ``arena/admin/autostart.py::state_snapshot`` for the
        response shape."""
        from arena.admin import autostart as _autostart
        snap = _autostart.state_snapshot(ctx.root_agent)
        return ctx.cors_json_response({"ok": True, **snap})

    @authed(ctx)
    async def handle_v1_autostart_set(request: web.Request) -> web.Response:
        """POST /v1/autostart/{transport} -- toggle autostart
        for one transport. Body: ``{"enabled": true|false}``.

        Guardrails:
          * unknown transport -> 400 with the list of registered names.
          * malformed body -> assumes ``enabled: false`` (safe default).
          * env override active -> the response includes an
            ``env_override_warning`` so the UI can explain why the
            checkbox refuses to move.
        """
        from arena.admin import autostart as _autostart

        transport = request.match_info.get("transport", "")
        if transport not in _autostart.TRANSPORTS:
            return ctx.cors_json_response(
                {"ok": False,
                 "error": f"unknown transport {transport!r}",
                 "registered": list(_autostart.TRANSPORTS)},
                status=400,
            )

        try:
            body = await request.json()
        except Exception:
            body = {}
        enabled = bool(body.get("enabled", False))

        cfg = request.app[APP_CFG]
        port = cfg.get("port", 8765)

        if enabled:
            try:
                _autostart.enable(transport, ctx.root_agent, port=port)
                changed = True
            except Exception as e:  # noqa: BLE001
                return ctx.cors_json_response(
                    {"ok": False, "error": f"could not enable: {e}"},
                    status=500,
                )
        else:
            try:
                changed = _autostart.disable(transport, ctx.root_agent)
            except Exception as e:  # noqa: BLE001
                return ctx.cors_json_response(
                    {"ok": False, "error": f"could not disable: {e}"},
                    status=500,
                )

        # Return post-change snapshot for just this transport so
        # the client can update its cached state without a second
        # round-trip.
        snap = _autostart.state_snapshot(ctx.root_agent)
        t_state = snap["transports"][transport]

        payload = {
            "ok": True,
            "transport": transport,
            "changed": changed,
            "state": t_state,
        }
        if t_state.get("env_override"):
            payload["env_override_warning"] = (
                f"ARENA_{transport.upper()}_AUTOSTART is set in the "
                "environment and will override the marker. Unset it "
                "in the service unit to fully disable autostart."
            )
        ctx.audit({"type": "autostart_set",
                   "transport": transport,
                   "enabled": enabled,
                   "changed": changed})
        return ctx.cors_json_response(payload)

    return {
        "autostart_get": handle_v1_autostart_get,
        "autostart_set": handle_v1_autostart_set,
    }
