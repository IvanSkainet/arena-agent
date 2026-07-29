"""v4.108.0 -- persistent Code Workbench project tools."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_code_project import handle_code_project_tool  # noqa: E402
from arena.workbench import projects  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def test_project_create_write_read_list_remove(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    out = projects.create("demo", [{"path": "main.py", "content": "print('hi')"}])
    assert out["ok"] is True
    assert projects.write("demo", "data/input.txt", "hello")["ok"] is True
    got = projects.read("demo", "data/input.txt")
    assert got["text"] == "hello"
    listing = projects.list_projects()
    assert listing["count"] == 1
    assert listing["projects"][0]["name"] == "demo"
    assert projects.remove("demo")["ok"] is True


def test_project_rejects_bad_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    try:
        projects.write("demo", "../x", "bad")
    except ValueError as e:
        assert "unsafe" in str(e)
    else:
        raise AssertionError("expected ValueError")


def test_project_run_delegates_to_runner(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    projects.create("demo", [{"path": "main.py", "content": "print('hi')"}])
    seen = {}
    monkeypatch.setattr(projects._posture, "load_posture", lambda: {"runtime": "any"})
    def fake_run(code, lang, posture, **kwargs):
        seen.update(lang=lang, **kwargs)
        return {"ok": True, "stdout": "ok"}
    monkeypatch.setattr(projects._runner, "run_code_sync", fake_run)
    out = projects.run("demo", lang="python3", entry="main.py", argv=["x"], artifacts=["out/*"])
    assert out["ok"] is True
    assert seen["lang"] == "python3"
    assert seen["entry"] == "main.py"
    assert seen["argv"] == ["x"]


def test_project_mcp_tool_and_policy(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    out = _parsed(handle_code_project_tool("code_project.create", {"name": "x", "files": []}, ctx=object()))
    assert out["ok"] is True
    assert classify_tool_risk("code_project.list") == "safe"
    assert classify_tool_risk("code_project.create") == "medium"
    assert classify_tool_risk("code_project.run") == "dangerous"


def test_project_run_passes_deps(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    projects.create("demo", [{"path": "main.py", "content": "print('hi')"}])
    seen = {}
    monkeypatch.setattr(projects._posture, "load_posture", lambda: {"runtime": "any"})
    def fake_run(code, lang, posture, **kwargs):
        seen.update(kwargs)
        return {"ok": True}
    monkeypatch.setattr(projects._runner, "run_code_sync", fake_run)
    projects.run("demo", lang="python3", entry="main.py", deps={"python": ["requests"]})
    assert seen["deps"] == {"python": ["requests"]}


def test_project_deps_install_and_run_uses_project_deps(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    projects.create("demo", [{"path": "main.py", "content": "print('hi')"}])
    monkeypatch.setattr(projects._posture, "load_posture", lambda: {"sandbox": "off", "network": "open", "runtime": "any"})
    monkeypatch.setattr(projects._runner, "_resolve_runtime", lambda lang: "python")
    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""
    monkeypatch.setattr(__import__("arena.autonomy.deps", fromlist=["subprocess"]).subprocess, "run", lambda *a, **k: _Proc())
    out = projects.deps_install("demo", lang="python3", deps={"python": ["humanize==4.14.0"]})
    assert out["ok"] is True
    seen = {}
    def fake_run(code, lang, posture, **kwargs):
        seen.update(kwargs)
        return {"ok": True}
    monkeypatch.setattr(projects._runner, "run_code_sync", fake_run)
    out = projects.run("demo", lang="python3", entry="main.py", use_project_deps=True)
    assert out["ok"] is True
    assert "PYTHONPATH" in seen["env"]


def test_project_run_use_project_deps_requires_off(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    projects.create("demo", [{"path": "main.py", "content": "print('hi')"}])
    monkeypatch.setattr(projects._posture, "load_posture", lambda: {"sandbox": "appcontainer", "runtime": "any"})
    out = projects.run("demo", lang="python3", entry="main.py", use_project_deps=True)
    assert out["ok"] is False
    assert "sandbox=off" in out["error"]
