"""MCP registry for net.*, secrets.*, sudo.* tools (v4.57.0)."""
from __future__ import annotations


NET_MCP_TOOLS = [
    {
        "name": "net.http",
        "description": (
            "Typed HTTP client. Only http/https to public hostnames "
            "(inherits SSRF allow-list from browser.read). Supports "
            "json/text/base64 body, params, headers, bearer/basic auth. "
            "auth.value can be a literal token OR 'secret:<key>' which "
            "resolves via secrets.get without leaking the value into "
            "step arguments. Response body capped at 2 MiB — textual "
            "MIMEs return .text (+.json when application/json), binary "
            "returns .base64. Timeout clamped [1s, 60s]."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "enum": ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"], "default": "GET"},
                "headers": {"type": "object", "additionalProperties": {"type": "string"}},
                "params": {"type": "object", "additionalProperties": {"type": "string"}},
                "json": {"description": "JSON body (any JSON-serialisable value)."},
                "text": {"type": "string", "description": "Plain-text body (mutually exclusive with json/base64)."},
                "base64": {"type": "string", "description": "Base64-encoded binary body."},
                "auth": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["bearer", "basic"]},
                        "value": {"type": "string", "description": "Token, or 'secret:<key>' to pull from secrets.json."},
                    },
                },
                "timeout": {"type": "number", "default": 20, "description": "Seconds, clamped [1, 60]."},
            },
            "required": ["url"],
        },
    },
    {
        "name": "secrets.get",
        "description": (
            "Read metadata for one secret from ~/.arena/secrets.json "
            "(or ARENA_SECRETS_PATH). Returns preview + length, NEVER "
            "the plaintext value — pass 'secret:<key>' to net.http.auth "
            "if you need the value on the wire."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"],
        },
    },
    {
        "name": "secrets.list",
        "description": "List available secret keys (values never returned).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "admin.run",
        "description": (
            "Cross-platform admin escalation. Linux/macOS proxies to sudo/Touch ID; "
            "Windows tries direct execution if already elevated, otherwise pops UAC "
            "via `powershell Start-Process -Verb RunAs`. Under the same "
            "BLOCK_PATTERNS gate as sudo.run and classified `dangerous` — always "
            "requires operator approval at the extension policy layer."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
                "timeout": {"type": "integer", "default": 30},
            },
            "required": ["cmd"],
        },
    },
    {
        "name": "sudo.run",
        "description": (
            "Run a command through 'sudo -n <cmd>' (non-interactive). "
            "Requires NOPASSWD sudoers configuration for the specific "
            "target command. Same BLOCK_PATTERNS as exec still apply "
            "(rm -rf /, mkfs, credential access, etc). POSIX only."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "cmd": {"type": "string"},
                "timeout": {"type": "integer", "default": 30},
            },
            "required": ["cmd"],
        },
    },
]

__all__ = ["NET_MCP_TOOLS"]
