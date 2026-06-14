"""Public index/health/API docs handler factory smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import PublicHandlerContext  # noqa: E402
from arena.public.handlers import PUBLIC_ENDPOINTS, make_public_handlers  # noqa: E402


def test_public_handlers_factory_outputs():
    ctx = PublicHandlerContext(
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        metrics=ub.BRIDGE_METRICS,
        version=ub.VERSION,
        now=lambda: ub.BRIDGE_METRICS["start_time"] + 1.0,
        hostname=lambda: "unit-host",
        bridge_port=lambda: 8765,
    )
    handlers = make_public_handlers(ctx)
    assert callable(handlers.index)
    assert callable(handlers.health)
    assert callable(handlers.api_docs)


def test_public_routes_registered():
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
    assert ("GET", "/") in paths
    assert ("GET", "/health") in paths
    assert ("GET", "/api-docs") in paths
    assert ("GET", "/openapi.json") in paths


def test_unified_public_handlers_bound_to_public_module():
    assert ub.handle_index.__module__ == "arena.public.handlers"
    assert ub.handle_health.__module__ == "arena.public.handlers"
    assert ub.handle_api_docs.__module__ == "arena.public.handlers"
    assert "/health" in PUBLIC_ENDPOINTS
