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
    assert callable(handlers.subagents_spawn)


def test_unified_routes_use_extracted_resource_handlers():
    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    for path in ["/v1/missions", "/v1/reports", "/v1/hooks", "/v1/agents", "/v1/subagents", "/v1/mission/show"]:
        assert ("GET", path) in paths
    assert ("POST", "/v1/subagents/spawn") in paths
