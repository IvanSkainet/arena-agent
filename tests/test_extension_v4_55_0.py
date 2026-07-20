"""v4.55.0 tests: scenarios merged into mission storage."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arena.scenarios import (
    InvalidScenario,
    ScenarioMissionStore,
    ScenarioNotFound,
    build_scenarios_runtime,
    resolve_missions_dir,
    SCENARIO_TEMPLATE_ID,
)
from arena.scenarios.mission_bridge import _mission_id, _find_by_name


@pytest.fixture
def tmp_store(monkeypatch, tmp_path):
    """Point ARENA_AGENT_HOME at tmp_path so missions live inside it."""
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    (tmp_path / "missions").mkdir(exist_ok=True)
    assert resolve_missions_dir() == tmp_path / "missions"
    return ScenarioMissionStore()


# --------------------------------------------------------------
# Storage lives at <agent_home>/missions/scenario-<slug>/mission.json
# --------------------------------------------------------------

def test_mission_id_is_deterministic():
    assert _mission_id("hello-world") == "scenario-hello-world"
    assert _mission_id("Foo Bar") == "scenario-foo-bar"


def test_save_creates_mission_json_with_scenario_template(tmp_store, tmp_path):
    tmp_store.save("mytest", json.dumps({
        "title": "My test",
        "steps": [{"id": "s", "tool": "sys.status", "arguments": {}}],
    }))
    mj = tmp_path / "missions" / "scenario-mytest" / "mission.json"
    assert mj.exists(), f"expected mission.json at {mj}"
    obj = json.loads(mj.read_text())
    assert obj["template"] == SCENARIO_TEMPLATE_ID
    assert obj["id"] == "scenario-mytest"
    assert obj["template_data"]["steps"][0]["tool"] == "sys.status"
    assert obj["template_data"]["name"] == "mytest"
    assert obj["state"] == "planned"


def test_save_returns_mission_id(tmp_store):
    saved = tmp_store.save("test", json.dumps({
        "steps": [{"id": "s", "tool": "sys.status"}],
    }))
    assert saved["mission_id"] == "scenario-test"
    assert saved["step_count"] == 1


def test_save_creates_logs_and_artifacts_subdirs(tmp_store, tmp_path):
    tmp_store.save("dirs", json.dumps({
        "steps": [{"id": "s", "tool": "sys.status"}],
    }))
    base = tmp_path / "missions" / "scenario-dirs"
    assert (base / "logs").is_dir()
    assert (base / "artifacts").is_dir()


def test_save_overwrite_preserves_runs_and_state(tmp_store, tmp_path):
    """Re-saving a scenario must not wipe execution history."""
    tmp_store.save("keep", json.dumps({
        "steps": [{"id": "s", "tool": "sys.status"}],
    }))
    # Simulate a run.
    tmp_store.append_run("keep", {"ok": True, "final": "hi"})
    obj = json.loads((tmp_path / "missions" / "scenario-keep" / "mission.json").read_text())
    assert len(obj["runs"]) == 1
    assert obj["state"] == "done"
    # Re-save the scenario.
    tmp_store.save("keep", json.dumps({
        "title": "updated",
        "steps": [{"id": "s", "tool": "sys.status"}, {"id": "r", "return": "hi"}],
    }))
    obj2 = json.loads((tmp_path / "missions" / "scenario-keep" / "mission.json").read_text())
    # runs[] preserved, state preserved.
    assert len(obj2["runs"]) == 1
    assert obj2["state"] == "done"
    assert obj2["title"] == "updated"
    assert len(obj2["template_data"]["steps"]) == 2


def test_save_overwrite_false_raises_when_exists(tmp_store):
    tmp_store.save("ow", json.dumps({"steps": [{"id": "s", "tool": "sys.status"}]}))
    with pytest.raises(InvalidScenario):
        tmp_store.save("ow", json.dumps({"steps": [{"id": "s", "tool": "sys.status"}]}),
                       overwrite=False)


def test_get_returns_expected_shape(tmp_store):
    tmp_store.save("shape", json.dumps({
        "title": "Shape test",
        "description": "verify",
        "steps": [{"id": "s", "tool": "sys.status", "arguments": {}}],
    }))
    got = tmp_store.get("shape")
    assert got["name"] == "shape"
    assert got["mission_id"] == "scenario-shape"
    assert got["doc"]["title"] == "Shape test"
    assert got["doc"]["steps"][0]["tool"] == "sys.status"
    # `source` is canonical JSON.
    parsed = json.loads(got["source"])
    assert parsed["name"] == "shape"


def test_get_missing_raises(tmp_store):
    with pytest.raises(ScenarioNotFound):
        tmp_store.get("nope")


def test_delete_removes_mission_directory(tmp_store, tmp_path):
    tmp_store.save("gone", json.dumps({"steps": [{"id": "s", "tool": "sys.status"}]}))
    d = tmp_path / "missions" / "scenario-gone"
    assert d.exists()
    tmp_store.delete("gone")
    assert not d.exists()


def test_delete_missing_raises(tmp_store):
    with pytest.raises(ScenarioNotFound):
        tmp_store.delete("nope")


def test_list_only_scenario_missions(tmp_store, tmp_path):
    """`ScenarioMissionStore.list` filters by template=='scenario'.
    Non-scenario missions in the same directory must not leak in."""
    tmp_store.save("s1", json.dumps({"steps": [{"id": "a", "tool": "sys.status"}]}))
    # Create a NON-scenario mission by hand (as mission_manager would).
    other = tmp_path / "missions" / "other-thing"
    other.mkdir(parents=True)
    (other / "mission.json").write_text(json.dumps({
        "id": "other-thing", "template": "cli-agent-core",
        "title": "Not a scenario", "state": "planned",
    }))
    lst = tmp_store.list()
    assert [x["name"] for x in lst] == ["s1"]


def test_list_metadata_fields(tmp_store):
    tmp_store.save("meta", json.dumps({
        "title": "Meta test",
        "description": "long desc",
        "steps": [
            {"id": "a", "tool": "sys.status"},
            {"id": "b", "tool": "fs.read", "arguments": {"path": "/x"}},
        ],
    }))
    entry = tmp_store.list()[0]
    assert entry["name"] == "meta"
    assert entry["title"] == "Meta test"
    assert entry["description"] == "long desc"
    assert entry["step_count"] == 2
    assert set(entry["tools"]) == {"sys.status", "fs.read"}
    assert entry["state"] == "planned"


# --------------------------------------------------------------
# History surface (mission.json.runs)
# --------------------------------------------------------------

def test_append_run_updates_mission_state(tmp_store, tmp_path):
    tmp_store.save("hist", json.dumps({"steps": [{"id": "s", "tool": "sys.status"}]}))
    tmp_store.append_run("hist", {"ok": True, "final": "yes"})
    obj = json.loads((tmp_path / "missions" / "scenario-hist" / "mission.json").read_text())
    assert obj["state"] == "done"
    assert len(obj["runs"]) == 1
    assert obj["runs"][0]["final"] == "yes"


def test_append_run_failed_marks_state_failed(tmp_store, tmp_path):
    tmp_store.save("fail", json.dumps({"steps": [{"id": "s", "tool": "sys.status"}]}))
    tmp_store.append_run("fail", {"ok": False, "error": "boom"})
    obj = json.loads((tmp_path / "missions" / "scenario-fail" / "mission.json").read_text())
    assert obj["state"] == "failed"


def test_load_history_returns_runs(tmp_store):
    tmp_store.save("h", json.dumps({"steps": [{"id": "s", "tool": "sys.status"}]}))
    for i in range(3):
        tmp_store.append_run("h", {"ok": True, "idx": i})
    hist = tmp_store.load_history("h")
    assert [r["idx"] for r in hist] == [0, 1, 2]


def test_history_capped_at_20(tmp_store):
    tmp_store.save("cap", json.dumps({"steps": [{"id": "s", "tool": "sys.status"}]}))
    for i in range(25):
        tmp_store.append_run("cap", {"ok": True, "idx": i})
    hist = tmp_store.load_history("cap")
    assert len(hist) == 20
    # Oldest dropped, latest kept.
    assert hist[0]["idx"] == 5
    assert hist[-1]["idx"] == 24


# --------------------------------------------------------------
# Runtime works against ScenarioMissionStore
# --------------------------------------------------------------

def test_runtime_end_to_end(tmp_store):
    tmp_store.save("e2e", json.dumps({
        "steps": [
            {"id": "s", "tool": "sys.status", "arguments": {}},
            {"id": "r", "return": "v={{ steps.s.result.version }}"},
        ],
    }))
    rt = build_scenarios_runtime(
        lambda t, a: {"ok": True, "version": "4.55.0"},
        storage=tmp_store,
    )
    run = rt.run("e2e", approved=True)
    assert run.ok
    assert run.final == "v=4.55.0"
    # Run appended to mission.runs.
    hist = tmp_store.load_history("e2e")
    assert len(hist) == 1


def test_runtime_uses_default_store_when_none_passed(monkeypatch, tmp_path):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    (tmp_path / "missions").mkdir()
    rt = build_scenarios_runtime(lambda t, a: {"ok": True})
    assert isinstance(rt.storage, ScenarioMissionStore)
    assert rt.storage.missions_dir == tmp_path / "missions"


# --------------------------------------------------------------
# Backward-compat guard: existing (non-scenario) missions untouched
# --------------------------------------------------------------

def test_non_scenario_missions_dir_is_left_alone(tmp_store, tmp_path):
    """v4.55.0 must not corrupt or delete missions that were
    created by mission_manager with other templates."""
    other = tmp_path / "missions" / "some-cli-agent"
    other.mkdir(parents=True)
    obj = {"id": "some-cli-agent", "template": "cli-agent-core",
           "title": "CLI agent self-test", "state": "done"}
    (other / "mission.json").write_text(json.dumps(obj, indent=2))
    (other / "logs").mkdir()
    # Save + delete a scenario next to it.
    tmp_store.save("meanwhile", json.dumps({
        "steps": [{"id": "s", "tool": "sys.status"}]}))
    tmp_store.delete("meanwhile")
    # The other mission is untouched.
    assert other.exists()
    assert json.loads((other / "mission.json").read_text()) == obj


def test_find_by_name_falls_back_to_template_data_name(tmp_store, tmp_path):
    """If someone saved a scenario with an unusual mission_id
    (e.g. renamed the dir), _find_by_name still resolves it
    by scanning template_data.name."""
    # Create a scenario mission with a non-canonical directory name.
    (tmp_path / "missions" / "renamed-dir").mkdir(parents=True)
    (tmp_path / "missions" / "renamed-dir" / "mission.json").write_text(json.dumps({
        "id": "renamed-dir",
        "template": SCENARIO_TEMPLATE_ID,
        "template_data": {
            "name": "custom-name",
            "steps": [{"id": "s", "tool": "sys.status"}],
        },
        "state": "planned",
    }))
    got = tmp_store.get("custom-name")
    assert got["mission_id"] == "renamed-dir"
