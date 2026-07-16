"""HTTP handlers + shared marker persistence for the v4.38.0
unified autostart feature.

Split out from ``arena/admin/handlers.py`` when that file
reached the 600-line runtime threshold. Kept in a sibling
module so ``handlers.py`` stays modular (same pattern the
v4.19.0 proposal handlers followed).

Exposes:

* Two HTTP handlers::

      GET  /v1/autostart              -- state_snapshot for every transport
      POST /v1/autostart/{transport}  -- toggle one transport

* ``persist_after_action(...)`` -- shared helper used by every
  per-transport start/stop HTTP handler (tailscale / cloudflared
  / ngrok in ``handlers.py``). Consolidates the "on successful
  start, write marker; on successful stop, remove marker;
  best-effort so a filesystem hiccup does not fail an otherwise
  successful start/stop" logic in one place.

The helper lives here (not in ``autostart.py``) because it is
a *handler-side* concern: it takes an aiohttp-style ``result``
dict, mutates it with the outcome fields the API contract
promises (``autostart_marked`` / ``autostart_cleared``), and
delegates the actual marker I/O to ``arena/admin/autostart.py``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from aiohttp import web

from arena.app_keys import APP_CFG
from arena.handler_helpers import authed


def persist_after_action(
    transport: str,
    action: str,
    ok: bool,
    port: int,
    root_agent: Path | str,
    result: dict,
) -> None:
    """Persist an autostart marker after a per-transport tunnel
    verb handler has run.

    Called immediately after ``handle_v1_<transport>_tunnel``
    finishes its start/stop work. Mutates the ``result`` dict
    with one of the two API-contract fields:

    * ``result["autostart_marked"] = True|False`` after a
      successful ``"start"`` -- the marker was (or wasn't)
      written to disk.
    * ``result["autostart_cleared"] = True|False`` after a
      successful ``"stop"`` -- the marker was (or wasn't) removed.

    Behavioural contract (locked in by
    ``tests/test_autostart_unified.py`` and the v4.22.1 test
    suite that continues to pass unmodified):

    * ``ok=False`` -> no-op. A failed start must NOT create a
      marker (would autostart-loop a broken configuration on
      every bridge reboot). A failed stop must NOT remove the
      marker (would silently disable autostart).
    * Any exception during marker I/O is swallowed and the
      corresponding boolean is set to False. Rationale: the
      marker is a persistence *hint*; a full-disk / read-only
      filesystem / permission error must never bubble up and
      fail an otherwise successful ``/v1/<transport>/tunnel/start``
      call. Operators can still see the failure via the
      response boolean, but the tunnel itself keeps working.
    * Any ``action`` other than ``"start"`` or ``"stop"`` (e.g.
      ``"status"``) is a no-op -- status calls have no autostart
      semantics.

    Args:
        transport: One of ``arena.admin.autostart.TRANSPORTS``
            (``"tailscale"`` / ``"cloudflared"`` / ``"ngrok"``).
        action: The verb the tunnel handler just ran --
            ``"start"``, ``"stop"``, or ``"status"``.
        ok: Whether the tunnel action itself succeeded.
        port: Bridge port; written into the marker payload for
            operator diagnostics.
        root_agent: Bridge install root; marker lives at
            ``root_agent / .<transport>_autostart``.
        result: Mutable response dict returned by the tunnel
            handler. Mutated in place with the appropriate
            boolean field.
    """
    # Nothing to persist when the tunnel action itself failed.
    # A failed start must NOT create a marker (would loop a
    # broken configuration on every bridge reboot). A failed
    # stop must NOT remove the marker (would silently disable
    # autostart).
    if not ok:
        return
    # Marker I/O is a *hint* -- never allow a filesystem error
    # to fail an otherwise successful tunnel action. If the
    # write / delete raises, we set the response boolean to
    # False so the caller can see what happened, but the tunnel
    # itself keeps working.
    try:
        from arena.admin import autostart as _autostart
        if action == "start":
            _autostart.enable(transport, root_agent, port=port)
            result["autostart_marked"] = True
        elif action == "stop":
            result["autostart_cleared"] = _autostart.disable(
                transport, root_agent)
        # Any other action (e.g. "status") is a no-op -- status
        # calls have no autostart semantics.
    except Exception:  # noqa: BLE001 -- see docstring rationale
        if action == "start":
            result["autostart_marked"] = False
        elif action == "stop":
            result["autostart_cleared"] = False


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
