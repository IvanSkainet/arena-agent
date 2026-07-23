"""MCP registry metadata for scenario orchestration tools.

Wired into ``arena.mcp.tool_registry.MCP_TOOLS`` alongside
``MISSION_MCP_TOOLS``. Introduced in v4.54.0 as part of the
scenario orchestration backbone.
"""
from __future__ import annotations


SCENARIO_MCP_TOOLS = [
    {
        "name": "scenario.list",
        "description": (
            "List all saved scenarios (name, title, description, step count, "
            "tools used, file path, mtime)."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "scenario.get",
        "description": (
            "Read a scenario by name and return its YAML source, parsed doc, "
            "and disk path."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"], "additionalProperties": False},
    },
    {
        "name": "scenario.save",
        "description": (
            "Save (create or overwrite) a scenario. Validates the YAML "
            "schema before writing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "source": {"type": "string", "description": "JSON (or YAML if enabled) source"}, "yaml": {"type": "string", "description": "Alias for source (legacy)"},
                "overwrite": {"type": "boolean", "default": True},
            },
            "required": ["name"], "additionalProperties": False},
    },
    {
        "name": "scenario.delete",
        "description": "Remove a scenario and its run history.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"], "additionalProperties": False},
    },
    {
        "name": "scenario.preview",
        "description": (
            "Preview a scenario: derived risk classification, step count, "
            "and tools used, without running any of them."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"], "additionalProperties": False},
    },
    {
        "name": "scenario.run",
        "description": (
            "Execute a scenario's steps in order, interpolating "
            "{{ steps.<id>.result.<field> }} templates. Returns per-step "
            "results plus a final return value. Set dry_run=true to skip "
            "actual tool invocations. Each step may declare a `retry` "
            "block ({attempts, delay_seconds, backoff}) and/or a "
            "`wait_for` block ({file, http, timeout_seconds, "
            "poll_seconds}) — see docs/scenarios/README.md."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "approve": {"type": "boolean", "default": True},
                "dry_run": {"type": "boolean", "default": False},
            },
            "required": ["name"], "additionalProperties": False},
    },
    {
        "name": "scenario.history",
        "description": "Read the last 20 recorded runs of a scenario.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"], "additionalProperties": False},
    },
]

__all__ = ["SCENARIO_MCP_TOOLS"]
