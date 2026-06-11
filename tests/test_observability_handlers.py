"""Observability handler factory smoke tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import ObservabilityHandlerContext  # noqa: E402
from arena.observability.handlers import make_observability_handlers  # noqa: E402


def test_observability_handlers_factory_outputs():
    ctx = ObservabilityHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        audit_path=ub.AUDIT,
        request_log_file=ub._REQ_LOG_FILE,
        read_tail=ub.read_tail,
        read_request_log=ub.read_request_log,
        audit_stats_sync=ub._audit_stats_sync,
        load_webhooks=ub._load_webhooks,
        save_webhooks=ub._save_webhooks,
        normalize_webhooks_config=ub.normalize_webhooks_config,
        audit=ub.audit,
    )
    handlers = make_observability_handlers(ctx)
    assert callable(handlers.audit)
    assert callable(handlers.audit_stats)
    assert callable(handlers.audit_log)
    assert callable(handlers.webhooks_get)
    assert callable(handlers.webhooks_set)


def test_unified_routes_use_extracted_observability_handlers():
    app = ub.make_app({"token": "test"})
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/audit") in paths
    assert ("GET", "/v1/audit/stats") in paths
    assert ("GET", "/v1/audit/log") in paths
    assert ("GET", "/v1/webhooks") in paths
    assert ("POST", "/v1/webhooks") in paths
