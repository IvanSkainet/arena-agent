"""v4.116.0 -- long-running Python Code Sessions."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_code_session import handle_code_session_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.workbench import sessions  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_code_session_tools_registered_and_policy():
    names = {t["name"] for t in MCP_TOOLS}
    assert {"code_session.start", "code_session.exec", "code_session.list", "code_session.stop", "code_session.stop_all"} <= names
    assert classify_tool_risk("code_session.start") == "dangerous"
    assert classify_tool_risk("code_session.exec") == "dangerous"
    assert classify_tool_risk("code_session.list") == "safe"


def test_session_start_requires_sandbox_off(monkeypatch):
    monkeypatch.setattr(sessions._posture, "load_posture", lambda: {"sandbox": "appcontainer"})
    out = sessions.start(lang="python3")
    assert out["ok"] is False
    assert "sandbox=off" in out["error"]


def test_session_python_stateful_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(sessions._posture, "load_posture", lambda: {"sandbox": "off", "runtime": "any"})
    out = sessions.start(lang="python3", name="t")
    assert out["ok"] is True, out
    sid = out["session_id"]
    try:
        r1 = sessions.exec_code(sid, "x = 40\nprint('set')")
        assert r1["ok"] is True and "set" in r1["stdout"]
        r2 = sessions.exec_code(sid, "print(x + 2)")
        assert r2["ok"] is True and "42" in r2["stdout"]
        listed = sessions.list_sessions()
        assert listed["count"] >= 1
    finally:
        sessions.stop(sid)


def test_session_mcp_list(monkeypatch):
    monkeypatch.setattr(sessions, "list_sessions", lambda: {"ok": True, "count": 0, "sessions": []})
    out = _parsed(handle_code_session_tool("code_session.list", {}, ctx=object()))
    assert out == {"ok": True, "count": 0, "sessions": []}
