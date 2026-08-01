"""Tests for v4.150.0: Mission Control, Async Autopilot, Gap Pipeline."""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena import (
    capability_gaps as gaps,  # noqa: E402
    mission_autopilot as ap,  # noqa: E402
    mission_control as mc,  # noqa: E402
)
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402


def _fake_ok(port, token, tool, arguments, timeout):
    return {"ok": True, "tool": tool}


def _fake_slow(port, token, tool, arguments, timeout):
    time.sleep(0.05)
    return {"ok": True, "tool": tool}


# ---- Mission Control ----

def test_control_status_structure(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(mc, "_mcp_call_safe", lambda port, token, tool, args=None, timeout=15: {"ok": True})
    result = mc.control_status(port=1, token="t")
    assert result["ok"] is True
    assert "ship" in result
    assert "autopilot" in result
    assert "capability_gaps" in result
    assert "scenarios" in result
    assert "desktop" in result
    assert "mobile" in result
    assert "timestamp" in result


def test_control_status_includes_gaps(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(mc, "_mcp_call_safe", lambda port, token, tool, args=None, timeout=15: {"ok": True})
    gaps.record(title="test gap", severity="high")
    result = mc.control_status(port=1, token="t")
    assert result["capability_gaps"]["open_count"] == 1
    assert result["capability_gaps"]["gaps"][0]["title"] == "test gap"


def test_control_status_includes_autopilot(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(mc, "_mcp_call_safe", lambda port, token, tool, args=None, timeout=15: {"ok": True})
    monkeypatch.setattr(ap, "_mcp_call", _fake_ok)
    ap.start(goal="mc test", steps=[{"id": "a", "tool": "x", "arguments": {}}],
             constraints=None, max_steps=1, timeout_per_step=10,
             create_record=False, scenario_name="", port=1, token="t")
    result = mc.control_status(port=1, token="t")
    assert result["autopilot"]["total"] >= 1


# ---- Async Autopilot ----

def test_start_async_returns_immediately(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", _fake_slow)
    result = ap.start_async(
        goal="async test",
        steps=[{"id": "a", "tool": "exec.echo", "arguments": {}}],
        create_record=False, port=1, token="t",
    )
    assert result["ok"] is True
    assert result["async"] is True
    assert result["status"] == "running"
    assert "run_id" in result
    # Wait for completion with generous timeout for slow CI
    s = {"status": "running"}
    for _ in range(100):
        time.sleep(0.1)
        s = ap.status(result["run_id"])
        if s.get("status") != "running":
            break
    assert s["ok"] is True
    assert s["status"] in ("nominal", "partial")
    assert s["step_count"] == 1


def test_start_async_cancel(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    gate = threading.Event()

    def blocking_call(port, token, tool, arguments, timeout):
        gate.wait(timeout=10)
        return {"ok": True, "tool": tool}

    monkeypatch.setattr(ap, "_mcp_call", blocking_call)
    result = ap.start_async(
        goal="cancel async test",
        steps=[{"id": f"s{i}", "tool": "exec.echo", "arguments": {}} for i in range(5)],
        create_record=False, port=1, token="t",
    )
    run_id = result["run_id"]
    time.sleep(0.05)  # Let thread start
    cancel_result = ap.cancel(run_id)
    assert cancel_result["ok"] is True
    assert cancel_result["status"] == "cancelling"
    gate.set()  # Unblock the call so the worker can see the cancel
    # Wait for worker to finish
    s = {"status": "running"}
    for _ in range(100):
        time.sleep(0.1)
        s = ap.status(run_id)
        if s.get("status") not in ("running",):
            break
    assert s["status"] == "cancelled"
    assert s["step_count"] < 5


def test_start_async_empty_goal(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    result = ap.start_async(goal="")
    assert result["ok"] is False


# ---- Cancel with background signal ----

def test_cancel_sync_still_works(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", _fake_ok)
    out = ap.start(goal="sync cancel", steps=[{"id": "a", "tool": "x", "arguments": {}}],
                   constraints=None, max_steps=1, timeout_per_step=10,
                   create_record=False, scenario_name="", port=1, token="t")
    run = ap._load(out["run_id"])
    run["status"] = "running"
    run.pop("finished_at", None)
    ap._save(run)
    result = ap.cancel(out["run_id"])
    assert result["ok"] is True
    assert result["status"] == "cancelled"


# ---- Capability Gap Promote ----

def test_promote_gap(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    g = gaps.record(title="missing mumu.tap", severity="high")
    gap_id = g["gap"]["id"]
    result = gaps.promote(gap_id=gap_id, run_now=False)
    assert result["ok"] is True
    assert result["status"] == "promoted"
    assert result["gap"]["status"] == "promoted"


def test_promote_gap_with_run(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", _fake_ok)
    g = gaps.record(title="missing desktop.screenshot MCP", severity="medium")
    gap_id = g["gap"]["id"]
    result = gaps.promote(gap_id=gap_id, run_now=True, port=1, token="t")
    assert result["ok"] is True
    assert "autopilot" in result
    assert result["autopilot"]["ok"] is True
    # Gap should have autopilot_run_id
    assert result["gap"].get("autopilot_run_id")


def test_promote_not_found(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    result = gaps.promote(gap_id="nonexistent")
    assert result["ok"] is False


def test_promote_already_resolved(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    g = gaps.record(title="resolved gap", severity="low")
    gaps.resolve(gap_id=g["gap"]["id"], resolution="fixed")
    result = gaps.promote(gap_id=g["gap"]["id"])
    assert result["ok"] is False


# ---- Capability Gap Report ----

def test_gap_report(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    gaps.record(title="gap1", severity="high")
    gaps.record(title="gap2", severity="medium")
    gaps.record(title="gap3", severity="high")
    r = gaps.gap_report()
    assert r["ok"] is True
    assert r["total"] == 3
    assert r["by_severity"]["high"] == 2
    assert r["by_severity"]["medium"] == 1
    assert "open" in r["by_status"]


# ---- Registry ----

def test_new_v4150_tools_in_registry():
    names = {t["name"] for t in MCP_TOOLS}
    assert "mission.autopilot_start_async" in names
    assert "mission.control_status" in names
    assert "capability_gap.promote" in names
    assert "capability_gap.report" in names


def test_control_status_schema():
    by_name = {t["name"]: t for t in MCP_TOOLS}
    schema = by_name["mission.control_status"]["inputSchema"]
    assert schema["type"] == "object"
    assert schema.get("additionalProperties") is False


def test_start_async_schema():
    by_name = {t["name"]: t for t in MCP_TOOLS}
    schema = by_name["mission.autopilot_start_async"]["inputSchema"]
    assert "goal" in schema["required"]


# ---- Backward compat ----

def test_existing_autopilot_still_works(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", _fake_ok)
    out = ap.start(goal="compat", steps=[{"id": "a", "tool": "x", "arguments": {}}],
                   constraints=None, max_steps=1, timeout_per_step=10,
                   create_record=False, scenario_name="", port=1, token="t")
    assert out["ok"] is True
    assert out["status"] == "nominal"


def test_existing_gaps_still_work(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    g = gaps.record(title="t")
    assert g["ok"] is True
    ls = gaps.list_gaps()
    assert ls["count"] == 1
    r = gaps.resolve(gap_id=g["gap"]["id"], resolution="done")
    assert r["ok"] is True
