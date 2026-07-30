"""Scenario flight record regressions."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.scenarios.flight_records import create_record, get_report, list_records  # noqa: E402
from arena.scenarios.mission_bridge import ScenarioMissionStore  # noqa: E402


def _save_demo(store: ScenarioMissionStore) -> None:
    doc = {
        "name": "demo-flight",
        "title": "Demo flight",
        "description": "demo",
        "steps": [{"id": "echo", "tool": "exec.echo", "arguments": {"text": "hi"}}],
    }
    store.save("demo-flight", json.dumps(doc), overwrite=True)


def test_flight_record_roundtrip(tmp_path):
    store = ScenarioMissionStore(tmp_path / "missions")
    _save_demo(store)
    out = create_record(
        "demo-flight",
        title="Demo proof",
        status="partial",
        outcome="Observer saw the real thing",
        boundary="local only",
        observations=[{"title": "Window", "value": "visible"}],
        artifacts=[{"path": "shot.png"}],
        worked=["attach"],
        not_worked=["override"],
        next_steps=["retry"],
        data={"value": 42},
        storage=store,
    )
    assert out["ok"] is True
    assert Path(out["json_path"]).exists()
    assert Path(out["markdown_path"]).exists()
    md = Path(out["markdown_path"]).read_text(encoding="utf-8")
    assert "# Demo proof" in md
    assert "Observer saw the real thing" in md
    assert "local only" in md

    listed = list_records("demo-flight", storage=store)
    assert listed["count"] == 1
    assert listed["records"][0]["record_id"] == out["record_id"]

    report = get_report("demo-flight", record_id=out["record_id"], storage=store)
    assert report["ok"] is True
    assert report["record"]["data"]["value"] == 42
    assert "Demo proof" in report["markdown"]


def test_scenario_flight_record_tools_registered():
    names = {tool["name"] for tool in MCP_TOOLS}
    assert "scenario.record" in names
    assert "scenario.records" in names
    assert "scenario.flight_report" in names
