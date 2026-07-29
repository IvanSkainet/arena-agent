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


def test_session_start_appcontainer_is_windows_only(monkeypatch):
    monkeypatch.setattr(sessions._posture, "load_posture", lambda: {"sandbox": "appcontainer"})
    monkeypatch.setattr(sessions.sys, "platform", "linux")
    out = sessions.start(lang="python3")
    assert out["ok"] is False
    assert "Windows-only" in out["error"]


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


def test_session_can_start_in_project_with_project_deps(monkeypatch, tmp_path):
    from arena.workbench import projects
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    projects.create("demo", [{"path": "main.py", "content": "print('hi')"}])
    deps = tmp_path / "code-projects" / "demo" / ".deps" / "python"
    deps.mkdir(parents=True)
    monkeypatch.setattr(sessions._posture, "load_posture", lambda: {"sandbox": "off", "runtime": "any"})
    out = sessions.start(lang="python3", name="proj", project="demo", use_project_deps=True)
    assert out["ok"] is True, out
    sid = out["session_id"]
    try:
        assert out["project"] == "demo"
        listed = sessions.list_sessions()
        row = next(r for r in listed["sessions"] if r["session_id"] == sid)
        assert row["project"] == "demo"
        assert row["use_project_deps"] is True
    finally:
        sessions.stop(sid)


def test_session_files_and_artifacts(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(sessions._posture, "load_posture", lambda: {"sandbox": "off", "runtime": "any"})
    out = sessions.start(lang="python3", name="files")
    assert out["ok"] is True, out
    sid = out["session_id"]
    try:
        wr = sessions.write_file(sid, "data/input.txt", "hello")
        assert wr["ok"] is True
        rd = sessions.read_file(sid, "data/input.txt")
        assert rd["text"] == "hello"
        ex = sessions.exec_code(sid, "import os\nos.makedirs('out', exist_ok=True)\nopen('out/result.txt','w').write('artifact-ok')", artifacts=["out/*.txt"])
        assert ex["ok"] is True
        assert ex["artifacts"][0]["path"] == "out/result.txt"
        assert ex["artifacts"][0]["text"] == "artifact-ok"
        assert ex["run_id"]
        files = sessions.list_files(sid)
        assert {f["path"] for f in files["files"]} >= {"data/input.txt", "out/result.txt"}
    finally:
        sessions.stop(sid)


def test_session_file_tools_policy_and_mcp(monkeypatch):
    names = {t["name"] for t in MCP_TOOLS}
    assert {"code_session.write", "code_session.read", "code_session.files", "code_session.artifacts"} <= names
    assert classify_tool_risk("code_session.read") == "safe"
    assert classify_tool_risk("code_session.files") == "safe"
    assert classify_tool_risk("code_session.artifacts") == "safe"
    assert classify_tool_risk("code_session.write") == "medium"
    monkeypatch.setattr(sessions, "read_file", lambda *a, **k: {"ok": True, "text": "x"})
    out = _parsed(handle_code_session_tool("code_session.read", {"session_id": "s", "path": "x"}, ctx=object()))
    assert out["text"] == "x"


def test_session_sweep_dry_run_and_stop(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(sessions._posture, "load_posture", lambda: {"sandbox": "off", "runtime": "any"})
    out = sessions.start(lang="python3", name="sweep")
    assert out["ok"] is True, out
    sid = out["session_id"]
    try:
        # Make it stale without sleeping.
        sessions._SESSIONS[sid].last_used_at -= 999
        dry = sessions.sweep(max_idle_sec=10, dry_run=True)
        assert dry["ok"] is True
        assert dry["selected_count"] >= 1
        assert any(x["session_id"] == sid and "idle" in x["reasons"] for x in dry["selected"])
        assert sessions._SESSIONS[sid].alive()
        swept = sessions.sweep(max_idle_sec=10)
        assert swept["stopped_count"] >= 1
        assert sid not in sessions._SESSIONS
    finally:
        sessions.stop(sid)


def test_session_limit(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setenv("ARENA_CODE_SESSION_MAX", "1")
    monkeypatch.setattr(sessions._posture, "load_posture", lambda: {"sandbox": "off", "runtime": "any"})
    first = sessions.start(lang="python3")
    assert first["ok"] is True, first
    try:
        second = sessions.start(lang="python3")
        assert second["ok"] is False
        assert "limit" in second["error"]
    finally:
        sessions.stop(first["session_id"])


def test_session_sweep_mcp_and_policy(monkeypatch):
    assert "code_session.sweep" in {t["name"] for t in MCP_TOOLS}
    assert classify_tool_risk("code_session.sweep") == "medium"
    monkeypatch.setattr(sessions, "sweep", lambda **kw: {"ok": True, "dry_run": kw.get("dry_run")})
    out = _parsed(handle_code_session_tool("code_session.sweep", {"max_idle_sec": 1, "dry_run": True}, ctx=object()))
    assert out == {"ok": True, "dry_run": True}



def test_appcontainer_session_replay_prototype(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(sessions.sys, "platform", "win32")
    monkeypatch.setattr(sessions._posture, "load_posture", lambda: {"sandbox": "appcontainer", "runtime": "allowlist", "runtimes": ["python3"]})
    monkeypatch.setattr(sessions, "_resolve_win32_runtime", lambda lang: "python.exe")
    calls = []

    def fake_run(code, lang, posture, **kwargs):
        calls.append(kwargs)
        return {"ok": True, "stdout": "ok\n", "stderr": "", "sandbox_action": "appcontainer", "enforced": {"network": True}, "artifacts": [{"path": "out/x.txt", "text": "artifact"}]}

    monkeypatch.setattr(sessions._runner, "run_code_sync", fake_run)
    out = sessions.start(lang="python3", name="fenced")
    assert out["ok"] is True
    assert out["mode"] == "appcontainer-replay"
    sid = out["session_id"]
    try:
        r1 = sessions.exec_code(sid, "x = 1")
        r2 = sessions.exec_code(sid, "print(x + 1)", artifacts=["out/*.txt"])
        assert r1["ok"] is True and r2["ok"] is True
        assert sessions._SESSIONS[sid].history == ["x = 1", "print(x + 1)"]
        assert calls[-1]["platform"] == "win32"
        assert (sessions._SESSIONS[sid].cwd / "out" / "x.txt").read_text() == "artifact"
        assert r2["artifacts"][0]["path"] == "out/x.txt"
    finally:
        sessions.stop(sid)
