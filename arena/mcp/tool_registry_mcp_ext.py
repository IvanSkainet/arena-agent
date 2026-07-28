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
                "timeout": {"type": "number", "default": 60,
                            "description": "Maximum seconds to wait for the external MCP tool (1..180). On timeout the external server is stopped."},
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
    {
        "name": "mcp.add",
        "description": (
            "Register an external MCP server in mcp/mcp.json so the agent can "
            "use its tools via mcp.ext_call. EITHER pass an explicit 'command' "
            "(+ 'args'/'env') to add ANY MCP server, e.g. "
            "{\"name\":\"desktop-commander\",\"command\":\"npx\","
            "\"args\":[\"-y\",\"@wonderwhy-er/desktop-commander\"]}; OR pass only "
            "'name' to install from the marketplace registry (git-venv servers "
            "like 'screenpilot' are cloned + venv'd automatically). Adding a "
            "server is the trust decision and requires approval; afterwards its "
            "tools are usable without per-call approval."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "Server name to register (used as the key in mcp.json)."},
                "command": {"type": "string",
                            "description": "Launcher (npx/uvx/uv/python/python3/node or a full path). Omit to install from the registry by name."},
                "args": {"type": "array", "items": {"type": "string"},
                         "description": "Command arguments (e.g. [\"-y\",\"<package>\"])."},
                "env": {"type": "object",
                        "description": "Extra environment variables for the server."},
            },
            "required": ["name"], "additionalProperties": False},
    },
    {
        "name": "mcp.remove",
        "description": "Remove a registered external MCP server from mcp/mcp.json (and stop it if running).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string",
                         "description": "Server name to remove from mcp.json."},
            },
            "required": ["name"], "additionalProperties": False},
    },
]

__all__ = ["MCP_EXT_MCP_TOOLS"]
