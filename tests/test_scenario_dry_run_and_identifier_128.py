"""Scenario dry runs must not mutate state, and a mission id must resolve.

Regression guard for #128.

Two defects, both reachable through `scenario.*`:

1. `ScenariosRuntime.run()` branched on `dry_run` per step but called
   `self._storage.append_run(...)` unconditionally at the end. A dry run
   therefore appended a synthetic run record and - via `append_run` - flipped
   the mission `state` to "done" and stamped `finished_at`. Because
   `promote_from_history` defaults to `runs[-1]`, the next promotion could
   build a scenario out of steps that never executed.

2. `_find_by_name` derives the directory as `scenario-<slug(name)>`, but
   `mission.catalog` reports the directory name itself. Pasting that id back
   in produced `scenario-scenario-<slug>`, the lookup missed, and the caller
   was told the scenario "has no history" - indistinguishable from a real
   empty history.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.scenarios import promotion  # noqa: E402
from arena.scenarios.mission_bridge import ScenarioMissionStore  # noqa: E402
from arena.scenarios.runtime import build_scenarios_runtime  # noqa: E402

SCENARIO_NAME = "dry-probe"
MISSION_ID = f"scenario-{SCENARIO_NAME}"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    (tmp_path / "missions").mkdir()
    st = ScenarioMissionStore()
    st.save(
        SCENARIO_NAME,
        json.dumps(
            {
                "name": SCENARIO_NAME,
                "title": "Dry probe",
                "steps": [{"id": "s1", "tool": "sys.status", "arguments": {}}],
            }
        ),
        overwrite=True,
    )
    return st


def _mission_json(tmp_path) -> dict:
    return json.loads((tmp_path / "missions" / MISSION_ID / "mission.json").read_text())


def test_dry_run_records_no_run_and_leaves_state_untouched(store, tmp_path):
    before = _mission_json(tmp_path)
    assert before["state"] == "planned"
    assert before.get("runs") == []

    calls: list[str] = []
    runtime = build_scenarios_runtime(
        lambda tool, args: (calls.append(tool), {"ok": True})[1], storage=store
    )

    result = runtime.run(SCENARIO_NAME, approved=True, dry_run=True)

    after = _mission_json(tmp_path)
    assert calls == [], "a dry run must not dispatch any tool"
    assert after["runs"] == [], "a dry run must not append a run record"
    assert after["state"] == "planned", "a dry run must not flip mission state"
    assert "finished_at" not in after or after.get("finished_at") == before.get("finished_at")
    assert result.to_dict()["dry_run"] is True


def test_real_run_still_records_and_completes(store, tmp_path):
    """The guard must not disable recording for genuine runs."""
    calls: list[str] = []
    runtime = build_scenarios_runtime(
        lambda tool, args: (calls.append(tool), {"ok": True})[1], storage=store
    )

    result = runtime.run(SCENARIO_NAME, approved=True, dry_run=False)

    after = _mission_json(tmp_path)
    assert calls == ["sys.status"]
    assert len(after["runs"]) == 1
    assert after["state"] == "done"
    assert result.to_dict()["dry_run"] is False


def test_dry_run_then_real_run_records_only_the_real_one(store, tmp_path):
    runtime = build_scenarios_runtime(lambda tool, args: {"ok": True}, storage=store)

    runtime.run(SCENARIO_NAME, approved=True, dry_run=True)
    runtime.run(SCENARIO_NAME, approved=True, dry_run=False)

    runs = _mission_json(tmp_path)["runs"]
    assert len(runs) == 1, f"history polluted by the dry run: {runs}"
    assert runs[0]["dry_run"] is False


def test_promotion_rejects_a_dry_run_record(store):
    """Defence in depth for histories already polluted before the fix."""
    dry_record = {
        "ok": True,
        "name": SCENARIO_NAME,
        "steps": [
            {
                "id": "s1",
                "tool": "sys.status",
                "ok": True,
                "arguments": {},
                "result": {"dry_run": True, "arguments": {}},
            }
        ],
    }

    with pytest.raises(ValueError) as excinfo:
        promotion.scenario_from_run(dry_record, name="promoted-from-dry")
    assert str(excinfo.value) == "run is a dry run and cannot be promoted"


def test_promotion_rejects_a_record_carrying_the_explicit_marker(store):
    """A record written after the fix is flagged, not shape-inferred."""
    record = {
        "ok": True,
        "name": SCENARIO_NAME,
        "dry_run": True,
        "steps": [
            {"id": "s1", "tool": "sys.status", "ok": True, "arguments": {}, "result": {"ok": True}}
        ],
    }

    with pytest.raises(ValueError) as excinfo:
        promotion.scenario_from_run(record, name="promoted-from-dry")
    assert str(excinfo.value) == "run is a dry run and cannot be promoted"


def test_promotion_accepts_a_real_run(store):
    real = {
        "ok": True,
        "name": SCENARIO_NAME,
        "dry_run": False,
        "steps": [
            {"id": "s1", "tool": "sys.status", "ok": True, "arguments": {}, "result": {"ok": True}}
        ],
    }

    doc = promotion.scenario_from_run(real, name="promoted-ok")

    assert [s["tool"] for s in doc["steps"] if s.get("tool")] == ["sys.status"]


def test_history_resolves_by_mission_id_as_well_as_scenario_name(store, tmp_path):
    """mission.catalog hands back the mission id; it must resolve."""
    runtime = build_scenarios_runtime(lambda tool, args: {"ok": True}, storage=store)
    runtime.run(SCENARIO_NAME, approved=True, dry_run=False)

    by_name = store.load_history(SCENARIO_NAME)
    by_id = store.load_history(MISSION_ID)

    assert len(by_name) == 1
    assert by_id == by_name, "the mission id must not be prefixed a second time"


def test_exists_rejects_an_invalid_name_instead_of_claiming_it_exists(store):
    """A name that fails validation must be reported as absent.

    `exists()` swallows the validation error; returning True there would make
    promote_from_history fall through to load_history and answer "no history"
    for a name that can never resolve.
    """
    for bad in ("../escape", "", "a/b", "x" * 200):
        assert store.exists(bad) is False, f"{bad!r} was reported as existing"


def test_mission_id_alias_requires_a_scenario_typed_mission(store, tmp_path):
    """Any mission id may start with "scenario-"; only scenarios may match.

    The directory scan below the alias enforces
    `template == SCENARIO_TEMPLATE_ID`, and the alias must not be a way around
    it - otherwise an unrelated mission answers as a scenario and its run
    history becomes promotable.
    """
    impostor = tmp_path / "missions" / "scenario-foo"
    impostor.mkdir()
    (impostor / "mission.json").write_text(
        json.dumps(
            {
                "id": "scenario-foo",
                "template": "cli-agent-core",
                "state": "done",
                "runs": [
                    {
                        "ok": True,
                        "steps": [
                            {
                                "id": "s",
                                "tool": "exec.run",
                                "ok": True,
                                "arguments": {},
                                "result": {"ok": True},
                            }
                        ],
                    }
                ],
            }
        )
    )

    assert store.exists("scenario-foo") is False
    assert store.load_history("scenario-foo") == []


def test_a_real_result_containing_a_dry_run_key_is_still_promotable(store):
    """A tool may legitimately return `dry_run` in its own payload.

    Judging on the key alone would refuse a genuine run. The runtime's dry-run
    branch emits exactly {"dry_run": True, "arguments": ...} - nothing else -
    so the shape, not the key, is the signal.
    """
    real = {
        "ok": True,
        "name": SCENARIO_NAME,
        "steps": [
            {
                "id": "s1",
                "tool": "net.http",
                "ok": True,
                "arguments": {"url": "https://example.test"},
                "result": {"dry_run": True, "status": 200, "body": "real response"},
            }
        ],
    }

    assert promotion._is_dry_run(real) is False
    doc = promotion.scenario_from_run(real, name="promoted-real")
    assert [s["tool"] for s in doc["steps"] if s.get("tool")] == ["net.http"]


def test_mission_id_alias_requires_an_actual_mission_file(store, tmp_path):
    """A bare directory named like a scenario mission must not resolve.

    The alias check needs both the directory and its mission.json; matching on
    either one would make an empty leftover directory shadow a real lookup.
    """
    stray = tmp_path / "missions" / "scenario-stray"
    stray.mkdir()

    assert store.exists("scenario-stray") is False
    assert store.load_history("scenario-stray") == []


def test_exists_distinguishes_missing_scenario_from_empty_history(store):
    assert store.exists(SCENARIO_NAME) is True
    assert store.exists(MISSION_ID) is True
    assert store.exists("no-such-scenario") is False
    # Present, but nothing recorded yet - the two states must not look alike.
    assert store.load_history(SCENARIO_NAME) == []


def test_promote_from_history_reports_not_found_rather_than_no_history(store):
    out = promotion.promote_from_history("no-such-scenario", name="x", storage=store)

    # Exact comparison: a substring assertion keeps passing when the message
    # or the payload keys are corrupted, which is how a broken error ships.
    assert out == {
        "ok": False,
        "error": "source scenario not found: no-such-scenario",
        "source": "no-such-scenario",
    }


def test_is_dry_run_ignores_malformed_step_entries(store):
    """Non-dict entries in `steps` must not be treated as dry-run steps.

    The filter is `isinstance(s, dict) and s.get("tool")`; loosening it to
    `or` makes a record with a stray string step raise AttributeError instead
    of being judged on its real tool steps.
    """
    record = {
        "ok": True,
        "name": SCENARIO_NAME,
        "steps": [
            "not-a-step",
            {"id": "s1", "tool": "sys.status", "ok": True, "arguments": {}, "result": {"ok": True}},
        ],
    }

    doc = promotion.scenario_from_run(record, name="promoted-mixed")

    assert [s["tool"] for s in doc["steps"] if s.get("tool")] == ["sys.status"]


def test_run_with_no_tool_steps_is_not_misreported_as_a_dry_run(store):
    """An empty run must keep its own diagnosis.

    `_is_dry_run` returns early on an empty step list because `all([])` is
    True - without that guard every run with nothing to promote would be
    blamed on a dry run instead of reporting that it has no steps.
    """
    empty = {"ok": True, "name": SCENARIO_NAME, "steps": []}

    assert promotion._is_dry_run(empty) is False
    with pytest.raises(ValueError) as excinfo:
        promotion.scenario_from_run(empty, name="promoted-empty")
    assert str(excinfo.value) == "run contains no promotable tool steps"


def test_is_dry_run_ignores_steps_without_a_tool(store):
    """`return:`-only steps carry no tool and must not decide the verdict."""
    record = {
        "ok": True,
        "name": SCENARIO_NAME,
        "steps": [
            {"id": "r1", "tool": "", "ok": True, "returned": {"x": 1}},
            {"id": "s1", "tool": "sys.status", "ok": True, "arguments": {}, "result": {"ok": True}},
        ],
    }

    assert promotion._is_dry_run(record) is False


def test_promote_from_history_reports_empty_history_for_a_real_scenario(store):
    out = promotion.promote_from_history(SCENARIO_NAME, name="x", storage=store)

    assert out["ok"] is False
    assert out["error"] == "source scenario has no history"


def test_promote_from_history_works_when_given_the_mission_id(store):
    runtime = build_scenarios_runtime(lambda tool, args: {"ok": True}, storage=store)
    runtime.run(SCENARIO_NAME, approved=True, dry_run=False)

    out = promotion.promote_from_history(MISSION_ID, name="promoted-by-id", storage=store)

    assert out["ok"] is True
    assert out["name"] == "promoted-by-id"


def test_promote_from_history_refuses_a_dry_run_only_history(store, tmp_path):
    """End-to-end: a history containing only a dry run cannot be promoted.

    Simulates a mission polluted before the fix by writing the record the old
    code would have appended.
    """
    path = tmp_path / "missions" / MISSION_ID / "mission.json"
    obj = json.loads(path.read_text())
    obj["runs"] = [
        {
            "ok": True,
            "name": SCENARIO_NAME,
            "steps": [
                {
                    "id": "s1",
                    "tool": "sys.status",
                    "ok": True,
                    "arguments": {},
                    "result": {"dry_run": True, "arguments": {}},
                }
            ],
        }
    ]
    path.write_text(json.dumps(obj))

    with pytest.raises(ValueError) as excinfo:
        promotion.promote_from_history(SCENARIO_NAME, name="from-dry", storage=store)
    assert str(excinfo.value) == "run is a dry run and cannot be promoted"
