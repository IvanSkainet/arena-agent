"""Handler + route wiring tests for live-metrics (v3.95.0)."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from aiohttp import web  # noqa: E402

import unified_bridge as ub  # noqa: E402
from arena.observability.live_metrics_handler import make_live_metrics_handlers  # noqa: E402


def _make_ctx(auth_ok: bool = True):
    def cors_json(body, status=200):
        return web.json_response(body, status=status)

    def require_auth(request):
        if auth_ok:
            return None
        return web.json_response({"ok": False, "error": "auth"}, status=401)

    return SimpleNamespace(
        require_auth=require_auth,
        cors_json_response=cors_json,
        record_request=MagicMock(),
    )


def _run(coro):
    return asyncio.run(coro)


def test_live_metrics_handler_returns_snapshot():
    ctx = _make_ctx()
    handlers = make_live_metrics_handlers(ctx)
    resp = _run(handlers["live_metrics"](MagicMock()))
    assert resp.status == 200
    body = json.loads(resp.body.decode())
    assert body["ok"] is True
    assert "cpu" in body and "memory" in body


def test_live_metrics_handler_enforces_auth():
    ctx = _make_ctx(auth_ok=False)
    handlers = make_live_metrics_handlers(ctx)
    resp = _run(handlers["live_metrics"](MagicMock()))
    assert resp.status == 401


def test_live_metrics_stream_handler_returns_401_without_auth():
    """The WebSocket route enforces the same Bearer auth as REST.
    When the caller lacks a token, the route returns the 401 JSON
    response instead of upgrading."""
    ctx = _make_ctx(auth_ok=False)
    handlers = make_live_metrics_handlers(ctx)
    resp = _run(handlers["live_metrics_stream"](MagicMock()))
    assert resp.status == 401


def test_live_metrics_stream_handler_rejects_when_cap_exceeded(monkeypatch):
    """When the module-level counter is already at the cap, new
    connections get a 429 err_json instead of the WebSocket
    upgrade. Uses monkeypatch to raise the counter for the test
    without touching production state permanently."""
    from arena.observability import live_metrics_handler as _lmh
    monkeypatch.setattr(_lmh, "_ACTIVE_STREAM_CLIENTS", 32)
    ctx = _make_ctx()
    handlers = make_live_metrics_handlers(ctx)
    resp = _run(handlers["live_metrics_stream"](MagicMock()))
    assert resp.status == 429
    body = json.loads(resp.body.decode())
    assert body["ok"] is False
    assert "too many" in body["error"]


def test_live_metrics_routes_registered():
    app = ub.make_app({
        "token": "test",
        "profile": "owner-shell",
        "root": Path("/tmp"),
        "active_exec": 0,
        "max_concurrent": 3,
        "audit": "audit",
        "timeout": 60,
        "max_timeout": 3600,
        "max_output": 2000000,
        "allow_any_cwd": False,
        "semaphore": asyncio.Semaphore(1),
    })
    paths = {
        (r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter"))
        for r in app.router.routes()
    }
    assert ("GET", "/v1/live-metrics") in paths
    assert ("GET", "/v1/live-metrics/stream") in paths


def test_live_metrics_in_route_registry():
    """v3.95.0: the /v1/live-metrics endpoints must live in the
    canonical route registry, not only in domain.py wiring."""
    from arena.route_registry.registry import ROUTES
    keys = {(m, p) for (m, p, *_rest) in ROUTES}
    assert ("GET", "/v1/live-metrics") in keys
    assert ("GET", "/v1/live-metrics/stream") in keys
