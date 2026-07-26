"""MCP registry for mcp.ext_* tools — use EXTERNAL MCP servers (v4.94.0)."""
from __future__ import annotations

MCP_EXT_MCP_TOOLS = [
    {
        "name": "mcp.ext_servers",
        "description": (
            "List external MCP servers registered in mcp/mcp.json (e.g. "
            "desktop-commander, screenpilot, filesystem) and whether each is "
            "currently running."
        ),
        "inputSchema": {"type": "object", "properties": {},
                        "additionalProperties": False},
    },
    {
        "name": "mcp.ext_tools",
        "description": (
            "Connect to a registered external MCP server (starting it if "
            "needed) and list the tools it exposes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "server": {"type": "string",
                           "description": "Server name as registered in mcp.json, e.g. 'desktop-commander'."},
                "refresh": {"type": "boolean", "default": False,
                            "description": "Re-query the server instead of using the cached tool list."},
            },
            "required": ["server"], "additionalProperties": False},
    },
    {
        "name": "mcp.ext_call",
        "description": (
            "Call a tool on a registered external MCP server (starting it if "
            "needed) and return its result. Use mcp.ext_tools to discover a "
            "server's tool names and their arguments. The external server runs "
            "on the bridge host with the bridge user's privileges."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "server": {"type": "string",
                           "description": "Server name as registered in mcp.json."},
                "tool": {"type": "string",
                         "description": "Tool name exposed by that server (see mcp.ext_tools)."},
                "arguments": {"type": "object",
                              "description": "Arguments object for the tool (schema depends on the tool)."},
            },
            "required": ["server", "tool"], "additionalProperties": False},
    },
    {
        "name": "mcp.ext_stop",
        "description": "Stop a running external MCP server (lifecycle control).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "server": {"type": "string",
                           "description": "Server name as registered in mcp.json."},
            },
            "required": ["server"], "additionalProperties": False},
    },
]

__all__ = ["MCP_EXT_MCP_TOOLS"]
