"""Web Gateway handler factory smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.gateway.handlers import make_gateway_handlers  # noqa: E402
from arena.gateway.runtime import GW_WHITELIST, gw_allowed  # noqa: E402
from arena.handler_context import GatewayHandlerContext  # noqa: E402


def test_gateway_allowed_preserves_whitelist_and_metachar_blocks():
    assert "agentctl sys status" in GW_WHITELIST
    assert gw_allowed("agentctl sys status")
    assert not gw_allowed("echo nope")
    assert not gw_allowed("agentctl sys status; rm -rf /tmp/nope")
    assert ub.gw_allowed("agentctl sys status") is True


def test_gateway_handlers_factory_outputs():
    ctx = GatewayHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        executor=ub._EXECUTOR,
        handle_rpc=ub.handle_rpc,
        subprocess_kwargs=ub._subprocess_kwargs,
    )
    handlers = make_gateway_handlers(ctx)
    assert callable(handlers.index)
    assert callable(handlers.tools)
    assert callable(handlers.run)
    assert callable(handlers.tool)


def test_gateway_routes_registered():
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
    assert ("GET", "/gateway") in paths
    assert ("GET", "/gateway/tools") in paths
    assert ("POST", "/run") in paths
    assert ("POST", "/tool") in paths
