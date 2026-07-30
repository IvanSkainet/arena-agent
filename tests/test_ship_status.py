"""v4.119.0 -- whole-ship status / preflight."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.mcp.tool_ship import handle_ship_tool  # noqa: E402

S = importlib.import_module("arena.ship.status")  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_ship_tools_registered_and_safe():
    names = {t["name"] for t in MCP_TOOLS}
    assert {"ship.status", "ship.preflight"} <= names
    assert classify_tool_risk("ship.status") == "safe"
    assert classify_tool_risk("ship.preflight") == "safe"


def test_ship_status_shape(monkeypatch):
    monkeypatch.setattr(S, "_bridge_status", lambda: {"ok": True, "version": "test"})
    monkeypatch.setattr(S._posture, "get_posture", lambda: {"ok": True, "risk": "low"})
    monkeypatch.setattr(S, "_transport_status", lambda: {"ok": True, "active": {"provider": "tailscale"}})
    monkeypatch.setattr(S, "_mcp_status", lambda: {"ok": True, "count": 0, "servers": []})
    monkeypatch.setattr(S, "_browser_status", lambda: {"ok": True, "browseract": {"installed": True}, "cdp": {"browser_binary": "/bin/chrome"}})
    monkeypatch.setattr(S, "_mobile_status", lambda: {"ok": True, "devices": {"devices": [{"serial": "dev", "state": "device"}]}})
    monkeypatch.setattr(S, "_desktop_status", lambda mcp: {"ok": True, "screenpilot_registered": False})
    monkeypatch.setattr(S, "_service_autostart_status", lambda: {"ok": True, "healthy": True})
    monkeypatch.setattr(S, "_post_update_smoke_status", lambda: {"ok": True, "pending": False, "last": None})
    monkeypatch.setattr(S, "_safe", lambda name, fn: fn())
    monkeypatch.setattr(S, "_safe", lambda name, fn: {"ok": True, "known_limits": []} if name == "workbench" else fn())
    out = S.status()
    assert out["ok"] is True
    assert out["risk"] == "low"
    assert set(["bridge", "posture", "transports", "mcp", "desktop", "browser", "mobile", "workbench", "autostart", "post_update_smoke", "known_issues", "next_actions"]) <= set(out)


def test_ship_preflight_warns_but_ready(monkeypatch):
    monkeypatch.setattr(S, "status", lambda: {
        "version": "test",
        "posture": {"risk": "low"},
        "transports": {"active": None},
        "workbench": {"ok": True, "projects": {"count": 0}, "sessions": {"count": 0}},
        "mcp": {"ok": True, "count": 0},
        "browser": {"cdp": {"browser_binary": None}, "browseract": {"installed": False}},
        "mobile": {"devices": {"devices": []}},
        "autostart": {"ok": True, "healthy": False, "trigger": "boot"},
        "post_update_smoke": {"ok": True, "last": {"attempted": True, "ok": False, "smoke": {"mode": "blocked"}}},
        "known_issues": [],
        "next_actions": [],
    })
    out = S.preflight()
    assert out["ok"] is True
    assert out["mode"] == "degraded"
    assert out["warnings"]


def test_ship_mcp_tools(monkeypatch):
    monkeypatch.setattr(S, "status", lambda: {"ok": True, "ship": 1})
    monkeypatch.setattr(S, "preflight", lambda: {"ok": True, "ready": True})
    assert _parsed(handle_ship_tool("ship.status", {}, ctx=object()))["ship"] == 1
    assert _parsed(handle_ship_tool("ship.preflight", {}, ctx=object()))["ready"] is True
