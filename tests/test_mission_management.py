"""Mission composition/runtime/MCP regressions."""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from aiohttp.test_utils import make_mocked_request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.handler_context import ResourceHandlerContext  # noqa: E402
from arena.mcp.tool_mission import handle_mission_tool  # noqa: E402
from arena.mcp.tool_registry import MCP_TOOLS  # noqa: E402
from arena.resources.handlers import make_resource_handlers  # noqa: E402
from arena.resources.missions_manage import compose_mission_draft, create_mission_from_draft, list_mission_templates  # noqa: E402
from arena.resources.missions_orchestration import propose_mission_bundle, recover_mission_bundle  # noqa: E402
import unified_bridge as ub  # noqa: E402



def test_mission_template_listing_and_compose_create(tmp_path):
    templates = list_mission_templates()
    assert templates["ok"] is True
    assert templates["count"] > 0
    composed = compose_mission_draft(goal="Fix a code bug in repo", context="pytest failing", constraints=["do not break tests"], build_plan=ub.build_plan)
    assert composed["ok"] is True
    assert composed["draft"]["template"] in {"code-tdd", "cli-agent-core"}
    created = create_mission_from_draft(missions_dir=tmp_path / "missions", draft=composed["draft"])
    assert created["ok"] is True
    assert (Path(created["path"]) / "mission.json").exists()
    assert (Path(created["path"]) / "PLAN.md").exists()



def test_mission_propose_bundle_can_create_and_run(tmp_path):
    composed = compose_mission_draft(goal="Fix repo test failures", context="Need reusable mission", build_plan=ub.build_plan)

    result = propose_mission_bundle(
        goal="Fix repo test failures",
        context="Need reusable mission",
        react_sync=lambda **kwargs: {"ok": True, "goal": kwargs["goal"], "iterations": [{"action": {"name": "bridge.status"}}], "summary": "observed", "memory_profile": "code"},
        reflect_sync=lambda **kwargs: {"ok": True, "goal": kwargs["goal"], "confidence": "medium"},
        compose_sync=lambda data: {"ok": True, "draft": composed["draft"], "plan": composed["plan"], "template_data": composed["template_data"]},
        create_sync=lambda data: create_mission_from_draft(missions_dir=tmp_path / "missions", draft=data["draft"], mission_id=data.get("mission_id", "")),
        run_sync=lambda data: {"ok": True, "mission_id": data["mission_id"], "exit_code": 0},
        create=True,
        run_now=True,
    )
    assert result["ok"] is True
    assert result["mission"]["created"]["ok"] is True
    assert result["mission"]["run"]["ok"] is True
    assert result["mission"]["draft"]["analysis"]["reflection"]["confidence"] == "medium"



def test_mission_handlers_and_registry(tmp_path):
    missions_dir = tmp_path / "missions"
    missions_dir.mkdir()
    composed = compose_mission_draft(goal="Investigate a browser workflow", context="Need reusable mission", build_plan=ub.build_plan)

    def _create(data):
        return create_mission_from_draft(missions_dir=missions_dir, draft=data.get("draft") or composed["draft"], mission_id=data.get("mission_id", ""))

    ctx = ResourceHandlerContext(
        require_auth=lambda request: None,
        record_request=lambda *args, **kwargs: None,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        list_missions_sync=lambda: [],
        list_reports_sync=lambda: [],
        hooks_list_sync=lambda: {"ok": True, "count": 0, "hooks": []},
        agents_list_sync=lambda: {"ok": True, "count": 0, "agents": []},
        subagents_list_sync=lambda: {"ok": True, "count": 0, "subagents": []},
        mission_show_sync=lambda name: {"ok": True, "name": name},
        mission_status_sync=lambda name: {"ok": True, "mission": {"name": name, "state": "planned"}},
        mission_report_sync=lambda name: {"ok": False, "status": 404, "error": "missing report"},
        mission_history_sync=lambda name: {"ok": True, "mission": {"name": name}, "runs": [], "step_logs": []},
        mission_catalog_sync=lambda data: {"ok": True, "total": 1, "matched": 1, "items": [{"name": "demo", "state": data.get("state") or "planned"}]},
        mission_templates_sync=list_mission_templates,
        mission_compose_sync=lambda data: compose_mission_draft(goal=data.get("goal", ""), context=data.get("context", ""), build_plan=ub.build_plan),
        mission_propose_sync=lambda data: {"ok": True, "goal": data.get("goal", ""), "mission": {"draft": composed["draft"]}},
        mission_create_sync=_create,
        mission_run_sync=lambda data: {"ok": True, "mission_id": data.get("mission_id", "demo"), "exit_code": 0},
        mission_rerun_sync=lambda data: {"ok": True, "mission_id": data.get("mission_id", "demo"), "rerun": True},
        mission_recover_sync=lambda data: {"ok": True, "mission_id": data.get("mission_id", "demo"), "recovery": {"suggested_action": "rerun_failed_step"}},
        mission_followup_sync=lambda data: {"ok": True, "mission_id": data.get("mission_id", "demo"), "followup": {"goal": data.get("goal", "next")}},
        mission_iterate_sync=lambda data: {"ok": True, "mission_id": data.get("mission_id", "demo"), "decision": {"suggested_action": "rerun_failed_step"}},
        subagent_spawn_sync=lambda data: {"ok": True},
        audit=lambda data: None,
    )
    handlers = make_resource_handlers(ctx)

    templates_req = make_mocked_request("GET", "/v1/mission/templates", headers={"Authorization": "Bearer t"})
    templates_resp = asyncio.run(handlers.mission_templates(templates_req))
    templates_data = json.loads(templates_resp.text)
    assert templates_data["ok"] is True
    assert templates_data["count"] > 0

    catalog_req = make_mocked_request("GET", "/v1/mission/catalog?state=planned&q=demo", headers={"Authorization": "Bearer t"})
    catalog_resp = asyncio.run(handlers.mission_catalog(catalog_req))
    catalog_data = json.loads(catalog_resp.text)
    assert catalog_data["ok"] is True
    assert catalog_data["items"][0]["state"] == "planned"

    compose_req = make_mocked_request("POST", "/v1/mission/compose", headers={"Authorization": "Bearer t"})

    async def _compose_json():
        return {"goal": "Fix repo test failures"}

    compose_req.json = _compose_json
    compose_resp = asyncio.run(handlers.mission_compose(compose_req))
    compose_data = json.loads(compose_resp.text)
    assert compose_data["ok"] is True
    assert compose_data["draft"]["goal"] == "Fix repo test failures"

    propose_req = make_mocked_request("POST", "/v1/mission/propose", headers={"Authorization": "Bearer t"})

    async def _propose_json():
        return {"goal": "Fix repo test failures", "create": False}

    propose_req.json = _propose_json
    propose_resp = asyncio.run(handlers.mission_propose(propose_req))
    propose_data = json.loads(propose_resp.text)
    assert propose_data["ok"] is True
    assert propose_data["goal"] == "Fix repo test failures"
    assert propose_data["mission"]["draft"]["template"]

    create_req = make_mocked_request("POST", "/v1/mission/create", headers={"Authorization": "Bearer t"})

    async def _create_json():
        return {"draft": compose_data["draft"]}

    create_req.json = _create_json
    create_resp = asyncio.run(handlers.mission_create(create_req))
    create_data = json.loads(create_resp.text)
    assert create_data["ok"] is True
    assert Path(create_data["path"]).exists()

    run_req = make_mocked_request("POST", "/v1/mission/run", headers={"Authorization": "Bearer t"})

    async def _run_json():
        return {"mission_id": create_data["mission_id"], "timeout": 120}

    run_req.json = _run_json
    run_resp = asyncio.run(handlers.mission_run(run_req))
    run_data = json.loads(run_resp.text)
    assert run_data["ok"] is True
    assert run_data["mission_id"] == create_data["mission_id"]

    recover_req = make_mocked_request("POST", "/v1/mission/recover", headers={"Authorization": "Bearer t"})

    async def _recover_json():
        return {"mission_id": create_data["mission_id"], "rerun_now": False}

    recover_req.json = _recover_json
    recover_resp = asyncio.run(handlers.mission_recover(recover_req))
    recover_data = json.loads(recover_resp.text)
    assert recover_data["ok"] is True
    assert recover_data["recovery"]["suggested_action"] == "rerun_failed_step"

    followup_req = make_mocked_request("POST", "/v1/mission/followup", headers={"Authorization": "Bearer t"})

    async def _followup_json():
        return {"mission_id": create_data["mission_id"], "goal": "next mission"}

    followup_req.json = _followup_json
    followup_resp = asyncio.run(handlers.mission_followup(followup_req))
    followup_data = json.loads(followup_resp.text)
    assert followup_data["ok"] is True
    assert followup_data["followup"]["goal"] == "next mission"

    iterate_req = make_mocked_request("POST", "/v1/mission/iterate", headers={"Authorization": "Bearer t"})

    async def _iterate_json():
        return {"mission_id": create_data["mission_id"], "compose_followup": True}

    iterate_req.json = _iterate_json
    iterate_resp = asyncio.run(handlers.mission_iterate(iterate_req))
    iterate_data = json.loads(iterate_resp.text)
    assert iterate_data["ok"] is True
    assert iterate_data["decision"]["suggested_action"] == "rerun_failed_step"

    names = [tool["name"] for tool in MCP_TOOLS]
    assert "mission.templates" in names
    assert "mission.status" in names
    assert "mission.report" in names
    assert "mission.history" in names
    assert "mission.catalog" in names
    assert "mission.compose" in names
    assert "mission.propose" in names
    assert "mission.create" in names
    assert "mission.run" in names
    assert "mission.rerun" in names
    assert "mission.recover" in names
    assert "mission.followup" in names
    assert "mission.iterate" in names
    ctx2 = type("Ctx", (), {"app_config": staticmethod(lambda: {"port": 8765, "token": "t"})})()
    assert handle_mission_tool("not-mission", {}, ctx=ctx2) is None



def test_mission_status_report_history_catalog_and_recover_helpers(tmp_path):
    missions_dir = tmp_path / "missions"
    mission_dir = missions_dir / "demo"
    logs = mission_dir / "logs"
    logs.mkdir(parents=True)
    (mission_dir / "mission.json").write_text(json.dumps({"id": "demo", "title": "Demo", "template": "cli-agent-core", "state": "failed", "draft": {"goal": "Fix deployment", "constraints": ["preserve logs"], "suggested_memory_profile": "ops"}, "runs": [{"ts": "now", "ok": False, "results": [{"cmd": "echo ok", "exit_code": 1, "stderr": "boom"}, {"cmd": "echo later", "exit_code": 0}]}], "created_at": "now"}), encoding="utf-8")
    (mission_dir / "REPORT.md").write_text("report body", encoding="utf-8")
    (logs / "step-01.json").write_text(json.dumps({"cmd": "echo ok", "exit_code": 1}), encoding="utf-8")
    success_dir = missions_dir / "done-one"
    (success_dir / "logs").mkdir(parents=True)
    (success_dir / "mission.json").write_text(json.dumps({"id": "done-one", "title": "Done One", "template": "code-tdd", "state": "done", "draft": {"goal": "Ship feature"}, "runs": [{"ts": "later", "ok": True, "results": [{"cmd": "pytest", "exit_code": 0}]}], "created_at": "later"}), encoding="utf-8")

    from arena.resources.mission_loops import followup_mission_bundle, iterate_mission_bundle
    from arena.resources.mission_state import catalog_missions, get_mission_history, get_mission_report, get_mission_status, infer_rerun_step
    from arena.resources.missions_manage import rerun_mission

    status = get_mission_status(missions_dir, "demo")
    assert status["ok"] is True
    assert status["mission"]["runs_count"] == 1
    assert status["mission"]["failed_steps_count"] == 1
    report = get_mission_report(missions_dir, "demo")
    assert report["ok"] is True
    assert report["content"] == "report body"
    history = get_mission_history(missions_dir, "demo")
    assert history["ok"] is True
    assert history["step_logs"][0]["exit_code"] == 1
    inferred = infer_rerun_step(missions_dir, "demo", failed_only=True)
    assert inferred["ok"] is True
    assert inferred["step"] == 1
    catalog = catalog_missions(missions_dir, state="failed", query="deploy", has_report=True)
    assert catalog["ok"] is True
    assert catalog["matched"] == 1
    assert catalog["items"][0]["name"] == "demo"

    import arena.resources.missions_manage as mm
    monkeypatch = __import__('pytest').MonkeyPatch()
    monkeypatch.setattr(mm, "run_mission", lambda **kwargs: {"ok": True, "mission_id": kwargs["mission_id"], "step": kwargs.get("step"), "rerun": True})
    rerun = rerun_mission(root_agent=tmp_path, missions_dir=missions_dir, mission_id="demo", failed_only=True, subprocess_kwargs=lambda: {})
    monkeypatch.undo()
    assert rerun["ok"] is True
    assert rerun["step"] == 1

    recovery = recover_mission_bundle(
        missions_dir=missions_dir,
        mission_id="demo",
        notes="Prefer minimal recovery.",
        compose_followup=True,
        create_followup=True,
        reflect_sync=lambda **kwargs: {"ok": True, "goal": kwargs["goal"], "confidence": "medium", "positives": ["observed failure"], "concerns": ["step 1 failed"], "suggested_next_steps": ["rerun the failed step first"]},
        compose_sync=lambda data: {"ok": True, "draft": {"goal": data["goal"], "template": data.get("template", "cli-agent-core")}, "plan": {"steps": [{"title": "rerun"}]}, "template_data": {"id": data.get("template", "cli-agent-core")}},
        create_sync=lambda data: {"ok": True, "mission_id": data.get("mission_id") or "followup-demo", "path": str(missions_dir / "followup-demo")},
        rerun_sync=lambda data: {"ok": True, "mission_id": data["mission_id"], "step": data.get("step"), "rerun": True},
        rerun_now=True,
    )
    assert recovery["ok"] is True
    assert recovery["recovery"]["suggested_action"] == "rerun_failed_step"
    assert recovery["recovery"]["suggested_rerun"]["step"] == 1
    assert recovery["recovery"]["followup"]["composed"]["ok"] is True
    assert recovery["recovery"]["followup"]["created"]["ok"] is True
    assert recovery["recovery"]["rerun"]["ok"] is True

    followup = followup_mission_bundle(
        recovery=recovery,
        notes="Prefer minimal recovery.",
        create=True,
        run_now=True,
        react_sync=lambda **kwargs: {"ok": True, "goal": kwargs["goal"], "iterations": [{"action": {"name": "bridge.status"}}], "summary": "followup react"},
        reflect_sync=lambda **kwargs: {"ok": True, "goal": kwargs["goal"], "confidence": "high", "positives": ["ready"]},
        compose_sync=lambda data: {"ok": True, "draft": {"goal": data["goal"], "template": data.get("template", "cli-agent-core")}, "plan": {"steps": [{"title": "followup"}]}, "template_data": {"id": data.get("template", "cli-agent-core")}},
        create_sync=lambda data: {"ok": True, "mission_id": data.get("mission_id") or "followup-run", "path": str(missions_dir / "followup-run")},
        run_sync=lambda data: {"ok": True, "mission_id": data["mission_id"], "exit_code": 0},
    )
    assert followup["ok"] is True
    assert followup["followup"]["created"]["ok"] is True
    assert followup["followup"]["run"]["ok"] is True
    assert followup["reflection"]["confidence"] == "high"

    iteration = iterate_mission_bundle(
        missions_dir=missions_dir,
        mission_id="demo",
        notes="Prefer minimal recovery.",
        compose_followup=True,
        create_followup=True,
        run_followup=True,
        react_sync=lambda **kwargs: {"ok": True, "goal": kwargs["goal"], "iterations": [{"action": {"name": "bridge.status"}}], "summary": "iterate react"},
        reflect_sync=lambda **kwargs: {"ok": True, "goal": kwargs["goal"], "confidence": "medium", "positives": ["ready"], "suggested_next_steps": ["continue"]},
        compose_sync=lambda data: {"ok": True, "draft": {"goal": data["goal"], "template": data.get("template", "cli-agent-core")}, "plan": {"steps": [{"title": "iterate"}]}, "template_data": {"id": data.get("template", "cli-agent-core")}},
        create_sync=lambda data: {"ok": True, "mission_id": data.get("mission_id") or "iterated-run", "path": str(missions_dir / "iterated-run")},
        rerun_sync=lambda data: {"ok": True, "mission_id": data["mission_id"], "step": data.get("step"), "rerun": True},
        run_sync=lambda data: {"ok": True, "mission_id": data["mission_id"], "exit_code": 0},
    )
    assert iteration["ok"] is True
    assert iteration["decision"]["suggested_action"] == "rerun_failed_step"
    assert iteration["followup"]["created"]["ok"] is True
    assert iteration["followup"]["run"]["ok"] is True



def test_mission_cli_run_uses_hook_helpers(monkeypatch, tmp_path):
    import arena.missions_cli.commands as mc

    mission_dir = tmp_path / "demo"
    logs = mission_dir / "logs"
    logs.mkdir(parents=True)
    (mission_dir / "mission.json").write_text(json.dumps({"id": "demo", "template": "cli-agent-core", "title": "Demo", "state": "planned", "runs": []}), encoding="utf-8")
    events = []

    monkeypatch.setattr(mc, "find_mission", lambda mid: mission_dir)
    monkeypatch.setattr(mc, "commands_for", lambda template: ["echo ok"])
    monkeypatch.setattr(mc, "run_cmd", lambda cmd, timeout=120: {"cmd": cmd, "exit_code": 0, "stdout": "ok", "stderr": "", "ts": mc.now()})
    monkeypatch.setattr(mc, "report_cmd", lambda a: None)
    monkeypatch.setattr(mc, "_fire_mission_hook", lambda event, target, args=None, exit_code=0: events.append((event, target, exit_code)))
    monkeypatch.setattr(mc, "_start_recording", lambda mission_id: None)
    monkeypatch.setattr(mc, "_stop_recording", lambda rec: None)

    args = type("Args", (), {"id": "demo", "step": None, "timeout": 5, "__dict__": {"id": "demo", "step": None, "timeout": 5}})()
    rc = mc.run_cmd_mission(args)
    assert rc is None or rc == 0
    updated = json.loads((mission_dir / "mission.json").read_text(encoding="utf-8"))
    assert updated["state"] == "done"
    assert events[0][0] == "pre_mission"
    assert events[-1][0] == "post_mission"
