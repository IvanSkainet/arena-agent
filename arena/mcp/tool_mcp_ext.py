"""MCP tools for using EXTERNAL MCP servers through the bridge (v4.94.0).

The bridge exposes its own tools; these tools let the agent also use
*external* MCP servers registered in ``mcp/mcp.json`` (Desktop-Commander,
ScreenPilot, the official filesystem/fetch/git servers, ...) by connecting
to them with the MCP client (``arena.mcp_client``) and calling their tools.

* ``mcp.ext_servers``            -- list registered servers + running status.
* ``mcp.ext_tools(server)``      -- connect and list a server's tools.
* ``mcp.ext_call(server,tool,..)``-- call a tool on an external server.
* ``mcp.ext_stop(server)``       -- stop a running server (lifecycle).
"""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.mcp_client import McpError, get_manager


def _result(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def _ext_servers(args: dict[str, Any]) -> dict[str, Any]:
    mgr = get_manager()
    servers = mgr.servers()
    out = []
    for name, cfg in sorted(servers.items()):
        st = mgr.status(name)
        out.append({
            "name": name,
            "command": cfg.get("command", ""),
            "args": cfg.get("args", []),
            "running": st["running"],
        })
    return {"ok": True, "count": len(out), "servers": out}


def _ext_tools(args: dict[str, Any]) -> dict[str, Any]:
    server = str(args.get("server", "") or "").strip()
    if not server:
        return {"ok": False, "error": "missing 'server' argument"}
    refresh = bool(args.get("refresh", False))
    try:
        tools = get_manager().list_tools(server, refresh=refresh)
    except McpError as e:
        return {"ok": False, "error": str(e)}
    slim = [{"name": t.get("name", ""),
             "description": t.get("description", "")} for t in tools]
    return {"ok": True, "server": server, "count": len(slim), "tools": slim}


def _ext_call(args: dict[str, Any]) -> dict[str, Any]:
    server = str(args.get("server", "") or "").strip()
    tool = str(args.get("tool", "") or "").strip()
    if not server or not tool:
        return {"ok": False, "error": "missing 'server' and/or 'tool' argument"}
    arguments = args.get("arguments") or args.get("args") or {}
    if not isinstance(arguments, dict):
        return {"ok": False, "error": "'arguments' must be an object"}
    try:
        res = get_manager().call_tool(server, tool, arguments)
    except McpError as e:
        return {"ok": False, "error": str(e)}
    res["server"] = server
    res["tool"] = tool
    return res


def _ext_stop(args: dict[str, Any]) -> dict[str, Any]:
    server = str(args.get("server", "") or "").strip()
    if not server:
        return {"ok": False, "error": "missing 'server' argument"}
    get_manager().stop(server)
    return {"ok": True, "server": server, "stopped": True}


def handle_mcp_ext_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "mcp.ext_servers":
        return _result(_ext_servers(args))
    if name == "mcp.ext_tools":
        return _result(_ext_tools(args))
    if name == "mcp.ext_call":
        return _result(_ext_call(args))
    if name == "mcp.ext_stop":
        return _result(_ext_stop(args))
    return None


__all__ = ["handle_mcp_ext_tool"]
