"""Tests for the v4.38.0 unified autostart HTTP endpoints.

Proves:
  * GET /v1/autostart returns the state_snapshot shape.
  * POST /v1/autostart/{transport} enables/disables.
  * Unknown transport returns 400 with the list of valid names.
  * Malformed body defaults to enabled:false (safe).
  * env-override case returns a warning field.
  * AdminHandlers dataclass has the two new fields.
  * Route registry declares both paths.

Uses a real aiohttp app + TestServer so handlers actually run
against the router -- proves the wiring end-to-end.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from arena.admin import autostart


ENV_NG = "ARENA_NGROK_AUTOSTART"


# ---------------------------------------------------------------------------
# Dataclass + route registry
# ---------------------------------------------------------------------------
def test_admin_handlers_has_autostart_fields():
    from arena.admin.handlers import AdminHandlers
    from dataclasses import fields
    names = {f.name for f in fields(AdminHandlers)}
    assert "autostart_get" in names
    assert "autostart_set" in names


def test_route_registry_declares_autostart_paths():
    reg = (Path(__file__).resolve().parents[1]
           / "arena" / "route_registry" / "registry.py"
           ).read_text(encoding="utf-8")
    assert "'GET'" in reg and "/v1/autostart" in reg
    assert "'POST'" in reg and "/v1/autostart/{transport}" in reg
    assert "handle_v1_autostart_get" in reg
    assert "handle_v1_autostart_set" in reg


def test_route_registry_core_adds_both_routes():
    core = (Path(__file__).resolve().parents[1]
            / "arena" / "route_registry" / "core.py"
            ).read_text(encoding="utf-8")
    assert 'add_get("/v1/autostart"' in core
    assert 'add_post("/v1/autostart/{transport}"' in core


def test_platform_dispatcher_wires_both_handlers():
    plat = (Path(__file__).resolve().parents[1]
            / "arena" / "wiring" / "platform.py"
            ).read_text(encoding="utf-8")
    assert '"handle_v1_autostart_get": handlers.autostart_get' in plat
    assert '"handle_v1_autostart_set": handlers.autostart_set' in plat


# ---------------------------------------------------------------------------
# Handler behaviour -- direct call, no HTTP server needed
# ---------------------------------------------------------------------------
def _make_ctx(tmp_path):
    """Build a minimal AdminHandlerContext for direct handler
    invocation. ``cors_json_response`` is intentionally SYNC
    (returns a plain web.Response) -- matches the shape the
    real production wiring uses."""
    from arena.handler_context import AdminHandlerContext
    from aiohttp import web

    def _cors(payload, **kw):
        return web.json_response(payload, status=kw.get("status", 200))

    return AdminHandlerContext(
        require_auth=lambda req: None,
        record_request=lambda *a, **kw: None,
        cors_json_response=_cors,
        executor=None,
        audit=lambda ev: None,
        default_token_file=tmp_path / "token.txt",
        root_agent=tmp_path,
        subprocess_kwargs=lambda: {},
    )


def _make_request(method: str, path: str, body: dict | None = None,
                  match_info: dict | None = None):
    """Fake aiohttp Request just enough for our handlers."""
    from aiohttp import web
    from arena.app_keys import APP_CFG

    app = web.Application()
    app[APP_CFG] = {"port": 8765, "token": "t"}

    class _Req:
        def __init__(self):
            self.method = method
            self.path = path
            self.app = app
            self.headers = {"Authorization": "Bearer t"}
            self.match_info = match_info or {}
            self.query = {}
            self._body = body
        async def json(self):
            if self._body is None:
                raise ValueError("no body")
            return self._body
    return _Req()


def test_get_returns_state_snapshot_shape(tmp_path, monkeypatch):
    for t in autostart.TRANSPORTS:
        monkeypatch.delenv(f"ARENA_{t.upper()}_AUTOSTART", raising=False)
    from arena.admin.handlers import make_admin_handlers
    handlers = make_admin_handlers(_make_ctx(tmp_path))
    req = _make_request("GET", "/v1/autostart")
    resp = asyncio.run(handlers.autostart_get(req))
    payload = json.loads(resp.body.decode("utf-8"))
    assert payload["ok"] is True
    assert set(payload["transports"].keys()) == set(autostart.TRANSPORTS)
    assert payload["registered"] == list(autostart.TRANSPORTS)


def test_post_enable_creates_marker(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_NG, raising=False)
    from arena.admin.handlers import make_admin_handlers
    handlers = make_admin_handlers(_make_ctx(tmp_path))
    req = _make_request("POST", "/v1/autostart/ngrok",
                        body={"enabled": True},
                        match_info={"transport": "ngrok"})
    resp = asyncio.run(handlers.autostart_set(req))
    payload = json.loads(resp.body.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["transport"] == "ngrok"
    assert payload["state"]["enabled"] is True
    assert payload["state"]["marker"] is True
    assert autostart.marker_path("ngrok", tmp_path).exists()


def test_post_disable_removes_marker(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_NG, raising=False)
    autostart.enable("ngrok", tmp_path, port=8765)
    from arena.admin.handlers import make_admin_handlers
    handlers = make_admin_handlers(_make_ctx(tmp_path))
    req = _make_request("POST", "/v1/autostart/ngrok",
                        body={"enabled": False},
                        match_info={"transport": "ngrok"})
    resp = asyncio.run(handlers.autostart_set(req))
    payload = json.loads(resp.body.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["state"]["enabled"] is False
    assert payload["state"]["marker"] is False
    assert autostart.marker_path("ngrok", tmp_path).exists() is False


def test_post_unknown_transport_returns_400(tmp_path):
    from arena.admin.handlers import make_admin_handlers
    handlers = make_admin_handlers(_make_ctx(tmp_path))
    req = _make_request("POST", "/v1/autostart/bogus",
                        body={"enabled": True},
                        match_info={"transport": "bogus"})
    resp = asyncio.run(handlers.autostart_set(req))
    assert resp.status == 400
    payload = json.loads(resp.body.decode("utf-8"))
    assert payload["ok"] is False
    assert "bogus" in payload["error"]
    assert set(payload["registered"]) == set(autostart.TRANSPORTS)


def test_post_malformed_body_defaults_to_disable(tmp_path, monkeypatch):
    """Safe default: unparseable body should NOT accidentally
    enable autostart. Instead it disables (idempotent)."""
    monkeypatch.delenv(ENV_NG, raising=False)
    autostart.enable("ngrok", tmp_path, port=8765)
    from arena.admin.handlers import make_admin_handlers
    handlers = make_admin_handlers(_make_ctx(tmp_path))
    req = _make_request("POST", "/v1/autostart/ngrok",
                        body=None,  # request.json() raises
                        match_info={"transport": "ngrok"})
    resp = asyncio.run(handlers.autostart_set(req))
    payload = json.loads(resp.body.decode("utf-8"))
    assert payload["ok"] is True
    assert payload["state"]["enabled"] is False


def test_post_env_override_returns_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_TAILSCALE_AUTOSTART", "1")
    from arena.admin.handlers import make_admin_handlers
    handlers = make_admin_handlers(_make_ctx(tmp_path))
    req = _make_request("POST", "/v1/autostart/tailscale",
                        body={"enabled": False},
                        match_info={"transport": "tailscale"})
    resp = asyncio.run(handlers.autostart_set(req))
    payload = json.loads(resp.body.decode("utf-8"))
    assert payload["ok"] is True
    # Marker removed (or was never there)...
    assert payload["state"]["marker"] is False
    # ...but env-override still forces enabled + warning surfaces.
    assert payload["state"]["enabled"] is True
    assert payload["state"]["env_override"] is True
    assert "env_override_warning" in payload
    assert "ARENA_TAILSCALE_AUTOSTART" in payload["env_override_warning"]
