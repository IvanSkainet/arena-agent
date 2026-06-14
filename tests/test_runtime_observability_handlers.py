"""Runtime metrics/log handler factory smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import RuntimeObservabilityHandlerContext  # noqa: E402
from arena.observability.runtime_handlers import make_runtime_observability_handlers  # noqa: E402


def _ctx(tmp_path: Path) -> RuntimeObservabilityHandlerContext:
    log_file = tmp_path / "bridge.log"
    log_file.write_text("2026-01-01 INFO hello\n2026-01-01 ERROR boom\n", encoding="utf-8")
    return RuntimeObservabilityHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        metrics=ub.BRIDGE_METRICS,
        metrics_lock=ub._metrics_lock,
        active_processes=ub.ACTIVE_PROCESSES,
        cdp_state=ub._cdp_state,
        watchdog_state=ub._watchdog_state,
        event_subscribers=ub._event_subscribers,
        tls_config=ub._tls_config,
        grpc_config=ub._grpc_config,
        cluster_state=ub._cluster_state,
        sandbox_config=ub._sandbox_config,
        otel_config=ub._otel_config,
        log_file=log_file,
        version=ub.VERSION,
        now=lambda: ub.BRIDGE_METRICS["start_time"] + 1.0,
        log_error=ub.log.error,
    )


def test_runtime_observability_handlers_factory_outputs(tmp_path):
    handlers = make_runtime_observability_handlers(_ctx(tmp_path))
    assert callable(handlers.metrics)
    assert callable(handlers.prometheus_metrics)
    assert callable(handlers.logs)


def test_runtime_observability_routes_registered():
    app = ub.make_app({
        "token": "test",
        "profile": "owner-shell",
        "root": Path("/tmp"),
        "active_exec": 0,
        "max_concurrent": 3,
        "audit": "audit",
        "timeout": 60,
        "max_timeout": 3600,
        "max_output": 2000000,
        "allow_any_cwd": False,
        "semaphore": asyncio.Semaphore(1),
    })
    paths = {(r.method, r.resource.get_info().get("path") or r.resource.get_info().get("formatter")) for r in app.router.routes()}
    assert ("GET", "/v1/metrics") in paths
    assert ("GET", "/metrics") in paths
    assert ("GET", "/v1/logs") in paths


def test_unified_handlers_bound_to_runtime_observability_module():
    assert ub.handle_v1_metrics.__module__ == "arena.observability.runtime_handlers"
    assert ub.handle_prometheus_metrics.__module__ == "arena.observability.runtime_handlers"
    assert ub.handle_v1_logs.__module__ == "arena.observability.runtime_handlers"
