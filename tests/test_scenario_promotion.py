"""v4.134.0 -- Scenario Promotion."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.extension_bridge.policy import classify_tool_risk  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.mcp.tool_scenarios import handle_scenario_tool  # noqa: E402
from arena.scenarios import promotion  # noqa: E402
from arena.scenarios.mission_bridge import ScenarioMissionStore  # noqa: E402


def _parsed(res):
    return json.loads(res["content"][0]["text"])


def _run_obj():
    return {
        "ok": True,
        "name": "source",
        "finished_at": "2026-01-01T00:00:00",
        "steps": [
            {"id": "first", "tool": "exec.echo", "ok": True, "arguments": {"text": "hi"}, "result": {"text": "hi"}},
            {"id": "final", "return": {"x": 1}, "returned": {"x": 1}},
        ],
    }


def test_scenario_promotion_tools_registered_and_policy():
    names = {t["name"] for t in MCP_TOOLS}
    assert {"scenario.promote_from_run", "scenario.promote_from_history"} <= names
    assert classify_tool_risk("scenario.promote_from_run") == "medium"
    assert classify_tool_risk("scenario.promote_from_history") == "medium"


def test_promote_from_run_saves_scenario(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    store = ScenarioMissionStore()
    out = promotion.promote_from_run(_run_obj(), name="promoted-run", storage=store)
    assert out["ok"] is True
    got = store.get("promoted-run")
    assert got["doc"]["steps"][0]["tool"] == "exec.echo"
    assert got["doc"]["steps"][0]["arguments"] == {"text": "hi"}


def test_promote_from_history(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    store = ScenarioMissionStore()
    src = json.dumps({"name": "source", "steps": [{"id": "a", "tool": "exec.echo", "arguments": {"text": "x"}}]})
    store.save("source", src, overwrite=True)
    store.append_run("source", _run_obj())
    out = promotion.promote_from_history("source", name="from-history", storage=store)
    assert out["ok"] is True
    assert out["source"] == "source"
    assert store.get("from-history")["doc"]["steps"][0]["tool"] == "exec.echo"


def test_scenario_promotion_mcp_handler(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    out = _parsed(handle_scenario_tool("scenario.promote_from_run", {"name": "mcp-promoted", "run": _run_obj()}, ctx=object()))
    assert out["ok"] is True
    assert out["name"] == "mcp-promoted"
