"""Resource handler factory smoke tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import ResourceHandlerContext  # noqa: E402
from arena.resources.handlers import make_resource_handlers  # noqa: E402


def test_resource_handlers_factory_outputs():
    ctx = ResourceHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        list_missions_sync=ub._list_missions_sync,
        list_reports_sync=ub._list_reports_sync,
        hooks_list_sync=ub._hooks_list_sync,
        agents_list_sync=ub._agents_list_sync,
        subagents_list_sync=ub._subagents_list_sync,
        mission_show_sync=ub._mission_show_sync,
        mission_status_sync=ub._mission_status_sync,
        mission_report_sync=ub._mission_report_sync,
        mission_history_sync=ub._mission_history_sync,
        mission_catalog_sync=ub._mission_catalog_sync,
        mission_templates_sync=ub._mission_templates_sync,
        mission_compose_sync=ub._mission_compose_sync,
        mission_propose_sync=lambda data: {"ok": True, "goal": data.get("goal", "")},
        mission_create_sync=ub._mission_create_sync,
        mission_run_sync=ub._mission_run_sync,
        mission_rerun_sync=lambda data: {"ok": True, "mission_id": data.get("mission_id", "demo"), "rerun": True},
        mission_recover_sync=lambda data: {"ok": True, "mission_id": data.get("mission_id", "demo"), "recovery": {"suggested_action": "rerun_failed_step"}},
        subagent_spawn_sync=ub._subagents_spawn_sync,
        audit=ub.audit,
    )
    handlers = make_resource_handlers(ctx)
    assert callable(handlers.missions)
    assert callable(handlers.reports)
    assert callable(handlers.hooks)
    assert callable(handlers.agents)
    assert callable(handlers.subagents)
    assert callable(handlers.mission_show)
    assert callable(handlers.mission_status)
    assert callable(handlers.mission_report)
    assert callable(handlers.mission_history)
    assert callable(handlers.mission_catalog)
    assert callable(handlers.mission_templates)
    assert callable(handlers.mission_compose)
    assert callable(handlers.mission_propose)
    assert callable(handlers.mission_create)
    assert callable(handlers.mission_run)
    assert callable(handlers.mission_rerun)
    assert callable(handlers.mission_recover)
    assert callable(handlers.subagents_spawn)


def test_unified_routes_use_extracted_resource_handlers():
    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    for path in ["/v1/missions", "/v1/reports", "/v1/hooks", "/v1/agents", "/v1/subagents", "/v1/mission/show", "/v1/mission/status", "/v1/mission/report", "/v1/mission/history", "/v1/mission/catalog", "/v1/mission/templates"]:
        assert ("GET", path) in paths
    for path in ["/v1/subagents/spawn", "/v1/mission/compose", "/v1/mission/propose", "/v1/mission/create", "/v1/mission/run", "/v1/mission/rerun", "/v1/mission/recover"]:
        assert ("POST", path) in paths
