"""v4.118.0 -- aggregated Workbench status."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.mcp.tool_workbench import handle_workbench_tool  # noqa: E402
from arena.workbench import status as W  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_workbench_status_registered_and_safe():
    assert "workbench.status" in {t["name"] for t in MCP_TOOLS}
    assert classify_tool_risk("workbench.status") == "safe"


def test_workbench_status_shape(monkeypatch):
    monkeypatch.setattr(W._posture, "get_posture", lambda: {"ok": True, "risk": "low"})
    monkeypatch.setattr(W.runtimes, "probe", lambda: {"ok": True, "runtimes": {}})
    monkeypatch.setattr(W.runtime_compat, "build", lambda runtime_status=None: {"ok": True, "known_limits": [], "matrix": []})
    monkeypatch.setattr(W.projects, "list_projects", lambda: {"ok": True, "count": 0, "projects": []})
    monkeypatch.setattr(W.sessions, "list_sessions", lambda: {"ok": True, "count": 0, "sessions": []})
    monkeypatch.setattr(W, "_artifact_store_summary", lambda: {"ok": True, "recent": []})
    out = W.status()
    assert out["ok"] is True
    assert set(["posture", "runtimes", "runtime_compat", "projects", "sessions", "artifacts", "known_limits", "next_actions"]) <= set(out)


def test_workbench_mcp_tool(monkeypatch):
    monkeypatch.setattr(W, "status", lambda: {"ok": True, "x": 1})
    out = _parsed(handle_workbench_tool("workbench.status", {}, ctx=object()))
    assert out == {"ok": True, "x": 1}
