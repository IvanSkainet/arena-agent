"""Resource runtime wrapper extraction tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.resources.runtime import ResourceRuntimeContext, make_resource_runtime  # noqa: E402


def _runtime(tmp_path: Path):
    return make_resource_runtime(ResourceRuntimeContext(
        missions_dir=tmp_path / "missions",
        reports_dir=tmp_path / "reports",
        hooks_dir=tmp_path / "hooks",
        agents_dir=tmp_path / "agents",
        subagents_dir=tmp_path / "subagents",
        bin_dir=tmp_path / "bin",
        root_agent=tmp_path,
        build_plan=ub.build_plan,
        subprocess_kwargs=lambda: {},
    ))


def test_resource_runtime_factory_outputs(tmp_path):
    runtime = _runtime(tmp_path)
    assert callable(runtime.list_missions_sync)
    assert callable(runtime.list_reports_sync)
    assert callable(runtime.hooks_list_sync)
    assert callable(runtime.agents_list_sync)
    assert callable(runtime.subagents_list_sync)
    assert callable(runtime.subagents_spawn_sync)
    assert callable(runtime.mission_show_sync)
    assert callable(runtime.mission_status_sync)
    assert callable(runtime.mission_report_sync)
    assert callable(runtime.mission_history_sync)
    assert callable(runtime.mission_catalog_sync)
    assert callable(runtime.mission_templates_sync)
    assert callable(runtime.mission_compose_sync)
    assert callable(runtime.mission_create_sync)
    assert callable(runtime.mission_run_sync)
    assert callable(runtime.mission_rerun_sync)


def test_unified_resource_runtime_bindings():
    assert ub._list_missions_sync.__module__ == "arena.resources.runtime"
    assert ub._list_reports_sync.__module__ == "arena.resources.runtime"
    assert ub._hooks_list_sync.__module__ == "arena.resources.runtime"
    assert ub._agents_list_sync.__module__ == "arena.resources.runtime"
    assert ub._subagents_list_sync.__module__ == "arena.resources.runtime"
    assert ub._subagents_spawn_sync.__module__ == "arena.resources.runtime"
    assert ub._mission_show_sync.__module__ == "arena.resources.runtime"
    assert ub._mission_status_sync.__module__ == "arena.resources.runtime"
    assert ub._mission_report_sync.__module__ == "arena.resources.runtime"
    assert ub._mission_history_sync.__module__ == "arena.resources.runtime"
    assert ub._mission_catalog_sync.__module__ == "arena.resources.runtime"
    assert ub._mission_templates_sync.__module__ == "arena.resources.runtime"
    assert ub._mission_compose_sync.__module__ == "arena.resources.runtime"
    assert ub._mission_create_sync.__module__ == "arena.resources.runtime"
    assert ub._mission_run_sync.__module__ == "arena.resources.runtime"


def test_resource_runtime_lists_and_shows(tmp_path):
    runtime = _runtime(tmp_path)
    (tmp_path / "missions").mkdir()
    (tmp_path / "missions" / "demo.md").write_text("mission", encoding="utf-8")
    mission_dir = tmp_path / "missions" / "demo-run"
    mission_dir.mkdir()
    (mission_dir / "mission.json").write_text('{"id":"demo-run","title":"Demo Run","template":"cli-agent-core","state":"done","draft":{"goal":"Ship feature"},"runs":[]}', encoding="utf-8")
    (tmp_path / "reports").mkdir()
    (tmp_path / "reports" / "report.txt").write_text("report", encoding="utf-8")

    missions = runtime.list_missions_sync()
    names = {m["name"] for m in missions}
    assert "demo" in names and "demo-run" in names
    assert runtime.mission_show_sync("demo")["ok"] is True
    status = runtime.mission_status_sync("demo-run")
    assert status["ok"] is True
    assert status["mission"]["name"] == "demo-run"
    history = runtime.mission_history_sync("demo-run")
    assert history["ok"] is True
    assert history["mission"]["name"] == "demo-run"
    catalog = runtime.mission_catalog_sync({"state": "done", "q": "Ship"})
    assert catalog["ok"] is True
    assert catalog["matched"] == 1
    assert catalog["items"][0]["name"] == "demo-run"
    assert runtime.mission_report_sync("demo-run")["ok"] is False
    assert runtime.list_reports_sync()[0]["name"] == "report.txt"
    assert runtime.hooks_list_sync() == {"ok": True, "count": 0, "hooks": []}
    assert runtime.agents_list_sync() == {"ok": True, "count": 0, "agents": []}
    assert runtime.subagents_list_sync() == {"ok": True, "count": 0, "subagents": []}
    assert runtime.mission_templates_sync()["count"] > 0
    composed = runtime.mission_compose_sync({"goal": "Fix a code bug in repo", "context": "pytest failing"})
    assert composed["ok"] is True
    created = runtime.mission_create_sync({"draft": composed["draft"]})
    assert created["ok"] is True
