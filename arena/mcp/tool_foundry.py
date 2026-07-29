"""MCP tools for Tool Foundry v1."""
from __future__ import annotations

import json
from typing import Any

from arena.foundry import tools as _foundry
from arena.mcp.tool_utils import text_content

FOUNDRY_TOOL_NAMES = ("tool_foundry.list", "tool_foundry.validate", "tool_foundry.publish")


def _res(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def handle_foundry_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "tool_foundry.list":
        return _res(_foundry.list_candidates())
    if name == "tool_foundry.validate":
        return _res(_foundry.validate(
            str(args.get("project") or ""),
            str(args.get("manifest_path") or _foundry.DEFAULT_MANIFEST),
            run_tests=bool(args.get("run_tests", True)),
        ))
    if name == "tool_foundry.publish":
        return _res(_foundry.publish(
            str(args.get("project") or ""),
            str(args.get("manifest_path") or _foundry.DEFAULT_MANIFEST),
            run_tests=bool(args.get("run_tests", True)),
        ))
    return None


FOUNDRY_TOOLS = [
    {"name": "tool_foundry.list", "description": "List Code Workbench projects that contain a Tool Foundry manifest (.arena-tool.json).", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "tool_foundry.validate", "description": "Validate a Code Workbench project's tool manifest and run its tests without publishing.", "inputSchema": {"type": "object", "properties": {"project": {"type": "string"}, "manifest_path": {"type": "string", "default": ".arena-tool.json"}, "run_tests": {"type": "boolean", "default": True}}, "required": ["project"], "additionalProperties": False}},
    {"name": "tool_foundry.publish", "description": "Validate a Code Workbench project manifest/tests, then publish it as a callable custom.<name> tool wrapping code_project.run.", "inputSchema": {"type": "object", "properties": {"project": {"type": "string"}, "manifest_path": {"type": "string", "default": ".arena-tool.json"}, "run_tests": {"type": "boolean", "default": True}}, "required": ["project"], "additionalProperties": False}},
]
