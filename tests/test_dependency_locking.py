"""v4.128.0 -- project dependency locking."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_code_project import handle_code_project_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.workbench import projects  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def _make_dist(path: Path, name="demo", version="1.0.0"):
    d = path / f"{name}-{version}.dist-info"
    d.mkdir(parents=True)
    (d / "METADATA").write_text(f"Name: {name}\nVersion: {version}\n", encoding="utf-8")


def test_lock_tools_registered_and_policy():
    names = {t["name"] for t in MCP_TOOLS}
    assert {"code_project.lock", "code_project.lock_verify"} <= names
    assert classify_tool_risk("code_project.lock") == "medium"
    assert classify_tool_risk("code_project.lock_verify") == "safe"


def test_project_lock_and_verify(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    projects.create("p", [{"path": "main.py", "content": "print('x')"}], overwrite=True)
    dep = tmp_path / "code-projects" / "p" / ".deps" / "python"
    _make_dist(dep, "six", "1.17.0")
    out = projects.lock("p", lang="python3", deps={"python": ["six==1.17.0"]})
    assert out["ok"] is True
    assert out["lock"]["resolved"]["python"] == ["six==1.17.0"]
    assert projects.lock_verify("p", lang="python3")["match"] is True
    _make_dist(dep, "other", "2.0.0")
    bad = projects.lock_verify("p", lang="python3")
    assert bad["match"] is False
    assert bad["mismatches"][0]["field"] == "resolved.python"


def test_project_run_strict_lock_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    projects.create("p", [{"path": "main.py", "content": "print('x')"}], overwrite=True)
    dep = tmp_path / "code-projects" / "p" / ".deps" / "python"
    _make_dist(dep, "six", "1.17.0")
    projects.lock("p", lang="python3")
    _make_dist(dep, "other", "2.0.0")
    monkeypatch.setattr(projects._posture, "load_posture", lambda: {"sandbox": "off", "runtime": "any"})
    called = {"run": False}
    monkeypatch.setattr(projects._runner, "run_code_sync", lambda *a, **k: called.__setitem__("run", True) or {"ok": True})
    out = projects.run("p", lang="python3", entry="main.py", lock_mode="strict")
    assert out["ok"] is False
    assert called["run"] is False
    assert "lock" in out


def test_lock_mcp_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    projects.create("p", [], overwrite=True)
    out = _parsed(handle_code_project_tool("code_project.lock", {"name": "p"}, ctx=object()))
    assert out["ok"] is True
    chk = _parsed(handle_code_project_tool("code_project.lock_verify", {"name": "p"}, ctx=object()))
    assert chk["match"] is True
