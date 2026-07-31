"""Tests for v4.149.0 Mission Autopilot Planner additions."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena import mission_autopilot as ap  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402


def _fake_call_ok(port, token, tool, arguments, timeout):
    return {"ok": True, "tool": tool, "arguments": arguments}


def _fake_call_fail(port, token, tool, arguments, timeout):
    if tool == "bad.tool":
        return {"ok": False, "error": "nope", "_raw_is_error": True}
    return {"ok": True, "tool": tool}


# ---- cancel ----

def test_cancel_running(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", _fake_call_ok)
    out = ap.start(goal="cancel test", steps=[{"id": "a", "tool": "exec.echo", "arguments": {}}],
                   constraints=None, max_steps=5, timeout_per_step=10,
                   create_record=False, scenario_name="", port=1, token="t")
    # Manually set status back to running to test cancel
    run = ap._load(out["run_id"])
    run["status"] = "running"
    run.pop("finished_at", None)
    ap._save(run)

    result = ap.cancel(out["run_id"])
    assert result["ok"] is True
    assert result["status"] == "cancelled"
    reloaded = ap._load(out["run_id"])
    assert reloaded["status"] == "cancelled"
    assert reloaded["outcome"] == "cancelled by operator"
    assert "finished_at" in reloaded


def test_cancel_already_completed(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", _fake_call_ok)
    out = ap.start(goal="done", steps=[{"id": "a", "tool": "exec.echo", "arguments": {}}],
                   constraints=None, max_steps=5, timeout_per_step=10,
                   create_record=False, scenario_name="", port=1, token="t")
    result = ap.cancel(out["run_id"])
    assert result["ok"] is False
    assert "already" in result["error"]


# ---- step ----

def test_step_appends(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", _fake_call_ok)
    out = ap.start(goal="step test", steps=[{"id": "a", "tool": "exec.echo", "arguments": {}}],
                   constraints=None, max_steps=5, timeout_per_step=10,
                   create_record=False, scenario_name="", port=1, token="t")
    assert out["step_count"] == 1
    result = ap.step(run_id=out["run_id"], tool="workbench.status", port=1, token="t")
    assert result["ok"] is True
    assert result["step_count"] == 2
    assert result["step"]["tool"] == "workbench.status"
    assert result["step"]["ok"] is True


def test_step_missing_tool(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", _fake_call_ok)
    out = ap.start(goal="t", steps=[{"id": "a", "tool": "x", "arguments": {}}],
                   constraints=None, max_steps=1, timeout_per_step=10,
                   create_record=False, scenario_name="", port=1, token="t")
    result = ap.step(run_id=out["run_id"], tool="")
    assert result["ok"] is False
    assert "required" in result["error"]


# ---- artifacts ----

def test_artifacts_collected(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))

    def fake(port, token, tool, arguments, timeout):
        return {"ok": True, "tool": tool, "path": "/some/file.txt", "screenshot": "/screen.png"}

    monkeypatch.setattr(ap, "_mcp_call", fake)
    out = ap.start(goal="art test", steps=[{"id": "a", "tool": "exec.echo", "arguments": {}}],
                   constraints=None, max_steps=5, timeout_per_step=10,
                   create_record=False, scenario_name="", port=1, token="t")
    arts = ap.artifacts(out["run_id"])
    assert arts["ok"] is True
    assert arts["artifact_count"] == 1
    assert arts["artifacts"][0]["path"] == "/some/file.txt"
    assert arts["artifacts"][0]["screenshot"] == "/screen.png"


# ---- from_goal (planner) ----

def test_from_goal_desktop(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", _fake_call_ok)
    out = ap.from_goal(goal="check desktop windows and screenshot",
                       max_steps=12, timeout_per_step=10,
                       create_record=False, port=1, token="t")
    assert out["ok"] is True
    assert out["planner"] == "keyword"
    assert any(s["tool"] == "desktop.windows" for s in out["planned_steps"])
    assert any(s["tool"] == "desktop.screenshot" for s in out["planned_steps"])


def test_from_goal_mobile(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", _fake_call_ok)
    out = ap.from_goal(goal="observe mobile phone state",
                       max_steps=12, timeout_per_step=10,
                       create_record=False, port=1, token="t")
    assert out["ok"] is True
    assert any(s["tool"] == "mobile.preflight" for s in out["planned_steps"])


def test_from_goal_mumu(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", _fake_call_ok)
    out = ap.from_goal(goal="check mumu emulator",
                       max_steps=12, timeout_per_step=10,
                       create_record=False, port=1, token="t")
    assert out["ok"] is True
    assert any(s["tool"] == "mumu.info" for s in out["planned_steps"])


def test_from_goal_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", _fake_call_ok)
    out = ap.from_goal(goal="do something completely abstract",
                       max_steps=12, timeout_per_step=10,
                       create_record=False, port=1, token="t")
    assert out["ok"] is True
    # Should fall back to default ship checklist
    assert any(s["tool"] == "ship.preflight" for s in out["planned_steps"])


def test_from_goal_empty(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    out = ap.from_goal(goal="", port=1, token="t")
    assert out["ok"] is False


def test_from_goal_multi_keyword(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", _fake_call_ok)
    out = ap.from_goal(goal="check ship status and desktop screenshot and mobile",
                       max_steps=20, timeout_per_step=10,
                       create_record=False, port=1, token="t")
    assert out["ok"] is True
    tools = {s["tool"] for s in out["planned_steps"]}
    assert "ship.preflight" in tools
    assert "desktop.windows" in tools
    assert "mobile.preflight" in tools


# ---- plan_from_goal unit ----

def test_plan_from_goal_unit():
    steps = ap._plan_from_goal("check desktop and mumu emulator")
    tools = [s["tool"] for s in steps]
    assert "desktop.windows" in tools
    assert "mumu.info" in tools
    # No duplicates
    ids = [s["id"] for s in steps]
    assert len(ids) == len(set(ids))


def test_plan_from_goal_no_match():
    steps = ap._plan_from_goal("xyzzy unrelated")
    # Falls back to defaults
    assert any(s["tool"] == "ship.preflight" for s in steps)


# ---- registry ----

def test_new_tools_in_registry():
    names = {t["name"] for t in MCP_TOOLS}
    assert "mission.autopilot_cancel" in names
    assert "mission.autopilot_step" in names
    assert "mission.autopilot_artifacts" in names
    assert "mission.autopilot_from_goal" in names


def test_new_tools_schemas():
    by_name = {t["name"]: t for t in MCP_TOOLS}
    # cancel requires run_id
    assert "run_id" in by_name["mission.autopilot_cancel"]["inputSchema"]["required"]
    # step requires run_id and tool
    assert "run_id" in by_name["mission.autopilot_step"]["inputSchema"]["required"]
    assert "tool" in by_name["mission.autopilot_step"]["inputSchema"]["required"]
    # artifacts requires run_id
    assert "run_id" in by_name["mission.autopilot_artifacts"]["inputSchema"]["required"]
    # from_goal requires goal
    assert "goal" in by_name["mission.autopilot_from_goal"]["inputSchema"]["required"]


# ---- existing tests still pass ----

def test_autopilot_start_still_works(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", _fake_call_ok)
    out = ap.start(goal="compat test", steps=[{"id": "a", "tool": "exec.echo", "arguments": {}}],
                   constraints=None, max_steps=5, timeout_per_step=10,
                   create_record=False, scenario_name="", port=1, token="t")
    assert out["ok"] is True
    assert out["status"] == "nominal"
    s = ap.status(out["run_id"])
    assert s["step_count"] == 1
    r = ap.report(out["run_id"])
    assert "Autopilot run" in r["markdown"]
    lst = ap.list_runs()
    assert lst["count"] >= 1
