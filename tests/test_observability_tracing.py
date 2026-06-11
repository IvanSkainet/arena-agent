"""OpenTelemetry tracing helper and handler factory smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import TracingHandlerContext  # noqa: E402
from arena.observability.tracing import (  # noqa: E402
    _otel_config,
    _otel_lock,
    _otel_record_span,
    _otel_should_sample,
    _otel_trace_id,
    _otel_traces,
    make_tracing_handlers,
)


def test_tracing_helpers_record_and_sample():
    original_enabled = _otel_config["enabled"]
    original_sample_rate = _otel_config["sample_rate"]
    try:
        _otel_config["enabled"] = True
        _otel_config["sample_rate"] = 1.0
        assert _otel_should_sample() is True
        trace_id = _otel_trace_id()
        with _otel_lock:
            before = len(_otel_traces)
        _otel_record_span(trace_id, "span1", "GET /unit", 12.34, {"unit": True})
        with _otel_lock:
            assert len(_otel_traces) == before + 1
            assert _otel_traces[-1]["trace_id"] == trace_id
            assert _otel_traces[-1]["resource"]["service.version"] == ub.VERSION
            _otel_traces.pop()
    finally:
        _otel_config["enabled"] = original_enabled
        _otel_config["sample_rate"] = original_sample_rate


def test_tracing_handlers_factory_outputs():
    ctx = TracingHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        version=ub.VERSION,
        log_info=ub.log.info,
    )
    handlers = make_tracing_handlers(ctx)
    assert callable(handlers.tracing)
    assert callable(handlers.traces_export)


def test_tracing_routes_registered():
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
    assert ("GET", "/v1/tracing") in paths
    assert ("POST", "/v1/tracing") in paths
    assert ("GET", "/v1/traces/export") in paths
    assert ("POST", "/v1/traces/export") in paths
