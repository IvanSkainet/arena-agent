"""System handler factory smoke tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import SystemHandlerContext  # noqa: E402
from arena.system.handlers import make_system_handlers  # noqa: E402


def test_system_handlers_factory_outputs():
    ctx = SystemHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        common_status=ub.common_status,
        version=ub.VERSION,
        clean_platform_name=ub.get_clean_platform_name,
    )
    handlers = make_system_handlers(ctx)
    assert callable(handlers.version)
    assert callable(handlers.info)
    assert callable(handlers.status)
    assert callable(handlers.config)


def test_unified_routes_use_extracted_system_handlers():
    app = ub.make_app({"token": "test", "profile": "owner-shell", "root": "/tmp", "active_exec": 0, "max_concurrent": 3, "audit": "audit"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    for path in ["/v1/version", "/v1/info", "/v1/status", "/v1/config"]:
        assert ("GET", path) in paths
