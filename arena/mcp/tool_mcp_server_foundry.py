"""MCP tools for MCP Server Foundry."""
from __future__ import annotations

import json
from typing import Any

from arena import mcp_server_foundry as F
from arena.mcp.tool_utils import text_content


def _res(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def handle_mcp_server_foundry_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "mcp_server.create":
        return _res(F.create(str(args.get("name") or ""), files=args.get("files") if isinstance(args.get("files"), list) else None,
                             command=str(args.get("command") or "") or None,
                             args=args.get("args") if isinstance(args.get("args"), list) else None,
                             entry=str(args.get("entry") or "server.py"), overwrite=bool(args.get("overwrite", False))))
    if name == "mcp_server.list":
        return _res(F.list_servers())
    if name == "mcp_server.test":
        return _res(F.test(str(args.get("name") or ""), tool=str(args.get("tool") or "") or None,
                           arguments=args.get("arguments") if isinstance(args.get("arguments"), dict) else None,
                           timeout=float(args.get("timeout", 15))))
    if name == "mcp_server.install":
        return _res(F.install(str(args.get("name") or ""), force=bool(args.get("force", False)),
                              test_tool=str(args.get("test_tool") or "") or None,
                              test_arguments=args.get("test_arguments") if isinstance(args.get("test_arguments"), dict) else None))
    return None


MCP_SERVER_FOUNDRY_TOOLS = [
    {"name": "mcp_server.create", "description": "Create an agent-authored external MCP server project under ARENA_AGENT_HOME/mcp-servers. If files are omitted, creates a minimal Python echo server.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "files": {"type": "array"}, "command": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}}, "entry": {"type": "string", "default": "server.py"}, "overwrite": {"type": "boolean", "default": False}}, "required": ["name"], "additionalProperties": False}},
    {"name": "mcp_server.list", "description": "List MCP Server Foundry projects.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "mcp_server.test", "description": "Start an authored MCP server one-shot, verify initialize/tools/list, and optionally tools/call.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "tool": {"type": "string"}, "arguments": {"type": "object"}, "timeout": {"type": "number", "default": 15}}, "required": ["name"], "additionalProperties": False}},
    {"name": "mcp_server.install", "description": "Test then install an authored MCP server as an external MCP server in mcp/mcp.json.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "force": {"type": "boolean", "default": False}, "test_tool": {"type": "string"}, "test_arguments": {"type": "object"}}, "required": ["name"], "additionalProperties": False}},
]
