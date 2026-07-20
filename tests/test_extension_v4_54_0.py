"""v4.54.0 tests: scenario orchestration backbone."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from arena.extension_bridge.policy import classify_tool_risk
from arena.mcp.tool_registry import MCP_TOOLS
from arena.scenarios import (
    InvalidScenario,
    ScenarioNotFound,
    ScenarioMissionStore,
    build_scenarios_runtime,
    derive_scenario_risk,
)
from arena.scenarios.runtime import render_template
from arena.scenarios.storage import parse_scenario_source, render_scenario_source


@pytest.fixture
def tmp_storage(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    (tmp_path / "missions").mkdir(exist_ok=True)
    # Force resolve to pick up env.
    from arena.scenarios import resolve_missions_dir
    assert resolve_missions_dir() == tmp_path / "missions"
    return ScenarioMissionStore()


# --------------------------------------------------------------
# MCP registry + policy classification
# --------------------------------------------------------------

def test_scenario_tools_registered():
    names = {t["name"] for t in MCP_TOOLS if t["name"].startswith("scenario.")}
    assert names == {
        "scenario.list", "scenario.get", "scenario.save", "scenario.delete",
        "scenario.preview", "scenario.run", "scenario.history",
    }


def test_scenario_read_tools_are_safe():
    for name in ("scenario.list", "scenario.get", "scenario.history", "scenario.preview"):
        assert classify_tool_risk(name) == "safe", name


def test_scenario_mutators_are_medium():
    for name in ("scenario.save", "scenario.delete"):
        assert classify_tool_risk(name) == "medium", name


def test_scenario_run_risk_is_derived_not_static():
    """scenario.run is deliberately NOT in the static safe/medium/
    dangerous tables — its risk is computed per-invocation from
    the wrapped tools."""
    assert classify_tool_risk("scenario.run") == "unknown"


# --------------------------------------------------------------
# YAML/JSON parse + validate
# --------------------------------------------------------------

def test_parse_json_source_ok():
    doc = parse_scenario_source(
        '{"name":"x","steps":[{"id":"s","tool":"sys.status","arguments":{}}]}'
    )
    assert doc["name"] == "x"
    assert len(doc["steps"]) == 1


def test_parse_rejects_empty_steps():
    with pytest.raises(InvalidScenario):
        parse_scenario_source('{"steps": []}')


def test_parse_rejects_missing_tool_and_return():
    with pytest.raises(InvalidScenario):
        parse_scenario_source('{"steps": [{"id":"x"}]}')


def test_parse_rejects_duplicate_step_ids():
    with pytest.raises(InvalidScenario):
        parse_scenario_source(
            '{"steps":[{"id":"a","tool":"sys.status"},{"id":"a","tool":"sys.status"}]}'
        )


def test_parse_rejects_non_dict_arguments():
    with pytest.raises(InvalidScenario):
        parse_scenario_source(
            '{"steps":[{"id":"a","tool":"sys.status","arguments":"nope"}]}'
        )


def test_render_scenario_source_is_json():
    text = render_scenario_source({"name": "x", "steps": [{"id": "s", "tool": "sys.status"}]})
    doc = json.loads(text)
    assert doc["name"] == "x"


# --------------------------------------------------------------
# Storage CRUD
# --------------------------------------------------------------

def test_storage_save_get_list_delete(tmp_storage):
    src = '{"name":"one","steps":[{"id":"s","tool":"sys.status","arguments":{}}]}'
    saved = tmp_storage.save("one", src)
    assert saved["name"] == "one"
    assert saved["step_count"] == 1

    got = tmp_storage.get("one")
    assert got["doc"]["name"] == "one"
    # `source` is the canonical json dump; contains the tool name.
    assert "sys.status" in got["source"]

    lst = tmp_storage.list()
    assert [s["name"] for s in lst] == ["one"]
    assert lst[0]["tools"] == ["sys.status"]

    tmp_storage.delete("one")
    assert tmp_storage.list() == []


def test_storage_get_missing_raises(tmp_storage):
    with pytest.raises(ScenarioNotFound):
        tmp_storage.get("nope")


def test_storage_delete_missing_raises(tmp_storage):
    with pytest.raises(ScenarioNotFound):
        tmp_storage.delete("nope")


def test_storage_list_skips_history_files_v4_55_0_missions_layout(tmp_storage):
    """v4.55.0 stores history INSIDE mission.json.runs -- no sidecar
    files exist anymore. This test replaces the v4.54.x behaviour."""
    tmp_storage.save("s1", '{"name":"s1","steps":[{"id":"a","tool":"sys.status"}]}')
    lst = tmp_storage.list()
    assert {s["name"] for s in lst} == {"s1"}


def test_storage_name_validation(tmp_storage):
    with pytest.raises(InvalidScenario):
        tmp_storage.save("Bad Name", '{"steps":[{"id":"s","tool":"sys.status"}]}')
    with pytest.raises(InvalidScenario):
        tmp_storage.save("../evil", '{"steps":[{"id":"s","tool":"sys.status"}]}')


def test_storage_history_roundtrip(tmp_storage):
    tmp_storage.save("h", '{"name":"h","steps":[{"id":"s","tool":"sys.status"}]}')
    for i in range(3):
        tmp_storage.append_run("h", {"ok": True, "final": f"v{i}"})
    hist = tmp_storage.load_history("h")
    assert [r["final"] for r in hist] == ["v0", "v1", "v2"]


def test_storage_history_cap(tmp_storage):
    HISTORY_KEEP = 20  # v4.55.0: baked into ScenarioMissionStore.append_run
    tmp_storage.save("h", '{"name":"h","steps":[{"id":"s","tool":"sys.status"}]}')
    for i in range(HISTORY_KEEP + 5):
        tmp_storage.append_run("h", {"ok": True, "idx": i})
    hist = tmp_storage.load_history("h")
    assert len(hist) == HISTORY_KEEP


# --------------------------------------------------------------
# Template rendering
# --------------------------------------------------------------

def test_template_now_and_env(monkeypatch):
    monkeypatch.setenv("FOO", "bar")
    out = render_template("env={{ env.FOO }} time={{ now }}", {"steps": {}})
    assert out.startswith("env=bar time=")
    # ISO-like format
    assert "T" in out


def test_template_missing_yields_empty(monkeypatch):
    out = render_template("x={{ env.NONEXISTENT }}y", {"steps": {}})
    assert out == "x=y"


def test_template_step_result_paths():
    ctx = {
        "steps": {
            "s": {
                "tool": "sys.status",
                "result": {"version": "4.54.0", "nested": {"key": "value"}, "arr": [10, 20]},
                "returned": None,
                "ok": True,
            }
        }
    }
    assert render_template("v={{ steps.s.result.version }}", ctx) == "v=4.54.0"
    assert render_template("k={{ steps.s.result.nested.key }}", ctx) == "k=value"
    assert render_template("i={{ steps.s.result.arr.1 }}", ctx) == "i=20"


def test_template_returned_lookup():
    ctx = {"steps": {"r": {"tool": "", "result": None, "returned": "hello", "ok": True}}}
    assert render_template("v={{ steps.r.returned }}", ctx) == "v=hello"


# --------------------------------------------------------------
# derive_scenario_risk
# --------------------------------------------------------------

def test_risk_all_safe():
    doc = {"steps": [{"tool": "sys.status"}, {"tool": "fs.read"}]}
    assert derive_scenario_risk(doc) == "safe"


def test_risk_promoted_by_dangerous_step():
    doc = {"steps": [{"tool": "sys.status"}, {"tool": "fs.write"}]}
    assert derive_scenario_risk(doc) == "dangerous"


def test_risk_medium_between():
    doc = {"steps": [{"tool": "sys.status"}, {"tool": "fs.create"}]}
    assert derive_scenario_risk(doc) == "medium"


def test_risk_return_only_scenario_is_safe():
    doc = {"steps": [{"id": "r", "return": "hello"}]}
    assert derive_scenario_risk(doc) == "safe"


# --------------------------------------------------------------
# Runtime.run integration
# --------------------------------------------------------------

def test_runtime_runs_and_records_history(tmp_storage):
    tmp_storage.save("t", json.dumps({
        "name": "t",
        "steps": [
            {"id": "s", "tool": "sys.status", "arguments": {}},
            {"id": "r", "return": "v={{ steps.s.result.version }}"},
        ],
    }))
    dispatched = []
    def dispatch(t, a):
        dispatched.append((t, a))
        return {"ok": True, "version": "9.9.9"}
    rt = build_scenarios_runtime(dispatch, storage=tmp_storage)
    run = rt.run("t", approved=True)
    assert run.ok
    assert dispatched == [("sys.status", {})]
    assert run.final == "v=9.9.9"
    # History appended.
    assert len(tmp_storage.load_history("t")) == 1


def test_runtime_stops_on_step_failure(tmp_storage):
    tmp_storage.save("t", json.dumps({
        "steps": [
            {"id": "a", "tool": "sys.status"},
            {"id": "b", "tool": "fs.read", "arguments": {"path": "/x"}},
            {"id": "c", "tool": "sys.status"},
        ],
    }))
    calls = []
    def dispatch(t, a):
        calls.append(t)
        if t == "fs.read":
            return {"ok": False, "error": "boom"}
        return {"ok": True}
    rt = build_scenarios_runtime(dispatch, storage=tmp_storage)
    run = rt.run("t", approved=True)
    assert not run.ok
    # Third step never runs.
    assert calls == ["sys.status", "fs.read"]


def test_runtime_continue_on_error(tmp_storage):
    tmp_storage.save("t", json.dumps({
        "steps": [
            {"id": "a", "tool": "fs.read", "arguments": {"path": "/x"}, "continue_on_error": True},
            {"id": "b", "tool": "sys.status"},
        ],
    }))
    calls = []
    def dispatch(t, a):
        calls.append(t)
        return {"ok": False, "error": "nope"} if t == "fs.read" else {"ok": True}
    rt = build_scenarios_runtime(dispatch, storage=tmp_storage)
    run = rt.run("t", approved=True)
    # Second step still fires because continue_on_error set on first.
    assert calls == ["fs.read", "sys.status"]


def test_runtime_dry_run_never_dispatches(tmp_storage):
    tmp_storage.save("t", json.dumps({
        "steps": [{"id": "a", "tool": "sys.status", "arguments": {}}],
    }))
    dispatched = []
    rt = build_scenarios_runtime(lambda t, a: dispatched.append(t) or {"ok": True}, storage=tmp_storage)
    run = rt.run("t", approved=True, dry_run=True)
    assert run.ok
    assert dispatched == []
    assert run.steps[0].result["dry_run"] is True


def test_runtime_approval_gate_for_dangerous(tmp_storage):
    tmp_storage.save("t", json.dumps({
        "steps": [{"id": "a", "tool": "fs.write", "arguments": {"path": "/x", "text": "hi"}}],
    }))
    rt = build_scenarios_runtime(lambda t, a: {"ok": True}, storage=tmp_storage)
    run = rt.run("t", approved=False)
    assert not run.ok
    assert "approval required" in (run.error or "")


def test_runtime_argument_interpolation(tmp_storage):
    tmp_storage.save("t", json.dumps({
        "steps": [
            {"id": "s", "tool": "sys.status", "arguments": {}},
            {"id": "u", "tool": "browser.read",
             "arguments": {"url": "https://example.com/v/{{ steps.s.result.version }}"}},
        ],
    }))
    seen_url = []
    def dispatch(t, a):
        if t == "sys.status":
            return {"ok": True, "version": "3.14"}
        if t == "browser.read":
            seen_url.append(a.get("url"))
            return {"ok": True}
        return {"ok": True}
    rt = build_scenarios_runtime(dispatch, storage=tmp_storage)
    run = rt.run("t", approved=True)
    assert run.ok
    assert seen_url == ["https://example.com/v/3.14"]


def test_runtime_preview_returns_derived_risk(tmp_storage):
    tmp_storage.save("mix", json.dumps({
        "steps": [{"id": "a", "tool": "sys.status"}, {"id": "b", "tool": "fs.write"}],
    }))
    rt = build_scenarios_runtime(lambda t, a: {"ok": True}, storage=tmp_storage)
    prev = rt.preview("mix")
    assert prev["risk"] == "dangerous"
    assert prev["step_count"] == 2
