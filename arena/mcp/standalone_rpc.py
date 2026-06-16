"""Standalone MCP JSON-RPC dispatcher."""
from __future__ import annotations

from arena.mcp.standalone_common import *  # noqa: F401,F403
from arena.mcp.standalone_tools import TOOLS, call_tool

def handle_rpc(msg: dict) -> dict | None:
    m = msg.get("method", ""); rid = msg.get("id")
    if m == "initialize":
        return rpc_result(rid, {"protocolVersion": "2025-03-26",
                                 "serverInfo": {"name": "arena-local-mcp-stream", "version": VERSION},
                                 "capabilities": {"tools": {"listChanged": False}}})
    if m == "tools/list":
        return rpc_result(rid, {"tools": TOOLS})
    if m == "tools/call":
        params = msg.get("params") or {}
        return rpc_result(rid, call_tool(params.get("name", ""), params.get("arguments") or {}))
    if m == "notifications/initialized":
        return None
    return rpc_error(rid, -32601, f"Method not found: {m}")
