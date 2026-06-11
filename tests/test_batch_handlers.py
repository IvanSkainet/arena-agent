"""Batch operation handler factory smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.batch.handlers import make_batch_handlers  # noqa: E402
from arena.handler_context import BatchHandlerContext  # noqa: E402


def test_batch_handlers_factory_outputs():
    ctx = BatchHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        emit_event=ub.emit_event,
        now=lambda: 1.0,
    )
    handlers = make_batch_handlers(ctx)
    assert callable(handlers.batch)


def test_batch_route_registered():
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
    assert ("POST", "/v1/batch") in paths
