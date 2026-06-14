"""MCP tool runtime extraction tests."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import unified_bridge as ub  # noqa: E402
from arena.mcp.tools import MCP_TOOLS, make_mcp_tool_runtime  # noqa: E402


def test_unified_mcp_tool_runtime_bound_to_module():
    assert ub.MCP_TOOLS is MCP_TOOLS
    assert ub.handle_rpc.__module__ == "arena.mcp.tools"
    assert ub.call_tool.__module__ == "arena.mcp.tools"
    assert ub.run_local.__module__ == "arena.mcp.tools"
    assert ub.run_sd.__module__ == "arena.mcp.tools"


def test_mcp_rpc_initialize_tools_and_unknown():
    init = ub.handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init["result"]["serverInfo"]["name"] == "arena-unified-bridge"

    tools = ub.handle_rpc({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert tools["result"]["tools"] is MCP_TOOLS

    assert ub.handle_rpc({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None

    unknown = ub.handle_rpc({"jsonrpc": "2.0", "id": 3, "method": "missing"})
    assert unknown["error"]["code"] == -32601


def test_mcp_call_tool_simple_tools():
    assert ub.call_tool("ping", {}) == {"content": [{"type": "text", "text": "pong"}]}
    assert ub.call_tool("echo", {"text": "hello"}) == {"content": [{"type": "text", "text": "hello"}]}
    assert ub.call_tool("unknown", {})["isError"] is True
