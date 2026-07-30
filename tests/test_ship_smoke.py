"""v4.137.0 -- Real Machine Smoke Matrix."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.mcp.tool_ship import handle_ship_tool  # noqa: E402
from arena.ship import smoke as S  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_ship_smoke_tools_registered_and_safe():
    names = {t["name"] for t in MCP_TOOLS}
    assert {"ship.smoke", "ship.smoke_history"} <= names
    assert classify_tool_risk("ship.smoke") == "safe"
    assert classify_tool_risk("ship.smoke_history") == "safe"


def test_ship_smoke_shape(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(S._posture, "get_posture", lambda: {"ok": True, "risk": "low"})
    monkeypatch.setattr(S._posture, "load_posture", lambda: {"risk": "low", "runtime": "any"})
    monkeypatch.setattr(S, "_code_smoke", lambda: {"ok": True, "run": {"sandbox_action": "test"}, "artifact_read": {"ok": True, "path": "out/x.json"}})
    monkeypatch.setattr(S.runtimes, "probe", lambda: {"ok": True, "runtimes": {}})
    monkeypatch.setattr(S.runtime_compat, "build", lambda rt: {"ok": True, "matrix": []})
    monkeypatch.setattr(S.mobile_preflight, "preflight", lambda: {"ok": True, "ready": True, "mode": "nominal"})
    monkeypatch.setattr(S.autostart_doctor, "status", lambda: {"ok": True, "healthy": True})
    monkeypatch.setattr(S.post_update_smoke, "status", lambda: {"ok": True, "pending": False, "last": None})
    monkeypatch.setattr(S, "_mcp_registry", lambda: {"ok": True, "count": 0, "servers": []})
    monkeypatch.setattr(S.platform, "system", lambda: "Windows")
    out = S.run()
    assert out["ok"] is True
    assert out["mode"] == "nominal"
    assert Path(out["report_path"]).exists()
    hist = S.history()
    assert hist["count"] == 1


def test_ship_smoke_mcp_tool(monkeypatch):
    monkeypatch.setattr(S, "run", lambda: {"ok": True, "mode": "nominal"})
    monkeypatch.setattr(S, "history", lambda limit=20: {"ok": True, "count": limit})
    assert _parsed(handle_ship_tool("ship.smoke", {}, ctx=object()))["mode"] == "nominal"
    assert _parsed(handle_ship_tool("ship.smoke_history", {"limit": 3}, ctx=object()))["count"] == 3
