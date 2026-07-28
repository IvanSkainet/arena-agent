"""v4.111.0 -- Code Workbench matrix runs."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_code_matrix import handle_code_matrix_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_code_matrix_registered_and_dangerous():
    assert "code_matrix.run" in {t["name"] for t in MCP_TOOLS}
    assert classify_tool_risk("code_matrix.run") == "dangerous"


def test_code_matrix_runs_one_shot_and_project(monkeypatch):
    import arena.mcp.tool_code_matrix as m

    monkeypatch.setattr(m._posture, "load_posture", lambda: {"runtime": "any"})
    monkeypatch.setattr(m._runner, "run_code_sync", lambda code, lang, posture, **kw: {"ok": True, "stdout": f"one:{lang}", "run_id": "r1"})
    monkeypatch.setattr(m._projects, "run", lambda project, **kw: {"ok": True, "stdout": f"project:{project}", "run_id": "r2"})
    out = _parsed(handle_code_matrix_tool("code_matrix.run", {"runs": [
        {"id": "a", "lang": "python3", "code": "print(1)"},
        {"id": "b", "project": "demo", "entry": "main.py"},
    ]}, ctx=object()))
    assert out["ok"] is True
    assert out["count"] == 2
    assert out["results"][0]["stdout"] == "one:python3"
    assert out["results"][1]["stdout"] == "project:demo"


def test_code_matrix_rejects_posture_override(monkeypatch):
    import arena.mcp.tool_code_matrix as m
    monkeypatch.setattr(m._posture, "load_posture", lambda: {"runtime": "any"})
    out = _parsed(handle_code_matrix_tool("code_matrix.run", {"runs": [
        {"id": "bad", "code": "x", "sandbox": "off"},
    ]}, ctx=object()))
    assert out["ok"] is False
    assert "operator-owned" in out["results"][0]["error"]


def test_code_matrix_limits_size():
    out = _parsed(handle_code_matrix_tool("code_matrix.run", {"runs": [{} for _ in range(9)]}, ctx=object()))
    assert out["ok"] is False
    assert "maximum" in out["error"]
