"""Mission Autopilot unit tests."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena import mission_autopilot as ap  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402


def test_autopilot_start_runs_steps_and_persists(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    calls = []

    def fake_call(port, token, tool, arguments, timeout):
        calls.append((tool, arguments))
        if tool == "bad.tool":
            return {"ok": False, "error": "nope"}
        return {"ok": True, "tool": tool, "arguments": arguments}

    monkeypatch.setattr(ap, "_mcp_call", fake_call)
    out = ap.start(
        goal="test autopilot",
        steps=[{"id": "a", "tool": "exec.echo", "arguments": {"text": "hi"}}, {"id": "b", "tool": "bad.tool"}],
        constraints=["local only"],
        max_steps=5,
        timeout_per_step=10,
        create_record=True,
        scenario_name="auto-test",
        port=8765,
        token="t",
    )
    assert out["ok"] is True
    assert out["status"] == "partial"
    assert (tmp_path / "autopilot" / "runs" / f"{out['run_id'].lower()}.json").exists()
    assert calls[0][0] == "exec.echo"
    assert any(c[0] == "scenario.save" for c in calls)
    assert any(c[0] == "scenario.record" for c in calls)
    status = ap.status(out["run_id"])
    assert status["step_count"] == 2
    report = ap.report(out["run_id"])
    assert "Autopilot run" in report["markdown"]


def test_autopilot_default_steps_and_registry(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    monkeypatch.setattr(ap, "_mcp_call", lambda port, token, tool, arguments, timeout: {"ok": True, "tool": tool})
    out = ap.start(goal="defaults", steps=None, constraints=None, max_steps=3, timeout_per_step=10, create_record=False, scenario_name="", port=1, token="t")
    assert out["step_count"] == 3
    listed = ap.list_runs()
    assert listed["count"] == 1
    names = {t["name"] for t in MCP_TOOLS}
    assert "mission.autopilot_start" in names
    assert "mission.autopilot_status" in names
    assert "mission.autopilot_report" in names
    assert "mission.autopilot_list" in names
