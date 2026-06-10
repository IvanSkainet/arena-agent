"""Service handler factory smoke tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import ServiceHandlerContext  # noqa: E402
from arena.service.handlers import make_service_handlers  # noqa: E402


def test_service_handlers_factory_outputs():
    ctx = ServiceHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        service_info_sync=ub._service_info_sync,
        sys_svc_sync=ub._sys_svc_sync,
        capabilities_sync=ub._capabilities_sync,
        spawn_respawn_helper=ub._spawn_respawn_helper,
        audit=ub.audit,
    )
    handlers = make_service_handlers(ctx)
    assert callable(handlers.service_info)
    assert callable(handlers.sys_svc)
    assert callable(handlers.capabilities)
    assert callable(handlers.restart)


def test_unified_routes_use_extracted_service_handlers():
    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/service/info") in paths
    assert ("GET", "/v1/sys/svc") in paths
    assert ("GET", "/v1/capabilities") in paths
    assert ("POST", "/v1/restart") in paths
