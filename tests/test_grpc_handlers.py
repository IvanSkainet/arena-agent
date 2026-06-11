"""gRPC-style secondary interface handler/runtime smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.grpc.handlers import make_grpc_handlers  # noqa: E402
from arena.grpc.runtime import GRPC_CONFIG, GRPC_METHOD_MAP, grpc_server_task, stop_grpc_server  # noqa: E402
from arena.handler_context import GrpcHandlerContext  # noqa: E402


def test_grpc_config_reexported_for_compatibility():
    assert ub._grpc_config is GRPC_CONFIG
    assert ub._grpc_server_task is grpc_server_task
    assert "Bridge/Status" in GRPC_METHOD_MAP


def test_grpc_handlers_factory_outputs():
    ctx = GrpcHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        server_task=ub._grpc_server_task,
        start_server=lambda cfg: None,
        stop_server=stop_grpc_server,
    )
    handlers = make_grpc_handlers(ctx)
    assert callable(handlers.grpc)


def test_grpc_routes_registered():
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
    assert ("GET", "/v1/grpc") in paths
    assert ("POST", "/v1/grpc") in paths


def test_grpc_stop_noop():
    assert asyncio.run(stop_grpc_server()) is False
