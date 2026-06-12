"""MCP transport handler/runtime smoke tests."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.handler_context import McpHandlerContext  # noqa: E402
from arena.mcp.handlers import make_mcp_handlers  # noqa: E402
from arena.mcp.runtime import MCP_SESSIONS, cleanup_mcp_sessions, now_ms, sid  # noqa: E402


def test_mcp_runtime_reexported_for_compatibility():
    assert ub.MCP_SESSIONS is MCP_SESSIONS
    assert callable(ub.sid)
    assert isinstance(sid(), str)
    assert isinstance(now_ms(), int)


def test_mcp_cleanup_sessions_removes_stale():
    sessions = {
        "old": {"created": 0},
        "new": {"created": now_ms()},
    }
    removed = cleanup_mcp_sessions(sessions)
    assert removed == 1
    assert "old" not in sessions
    assert "new" in sessions


def test_mcp_handlers_factory_outputs():
    ctx = McpHandlerContext(
        require_auth=ub.require_auth,
        record_request=ub._record_request,
        cors_json_response=ub._cors_json_response,
        handle_rpc=ub.handle_rpc,
        log_error=ub.log.error,
    )
    handlers = make_mcp_handlers(ctx)
    assert callable(handlers.mcp_post)
    assert callable(handlers.mcp_delete)
    assert callable(handlers.sse)
    assert callable(handlers.sse_messages)
    assert callable(handlers.ws)


def test_mcp_routes_registered():
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
    assert ("POST", "/mcp") in paths
    assert ("DELETE", "/mcp") in paths
    assert ("GET", "/sse") in paths
    assert ("POST", "/messages") in paths
    assert ("GET", "/ws") in paths


def test_mcp_handle_rpc_initialize_and_tools():
    init = ub.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init["result"]["serverInfo"]["name"] == "arena-unified-bridge"
    tools = ub.handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert tools["result"]["tools"]
