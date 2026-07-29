"""MCP tools for Workbench/ship status."""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.workbench import status as _status

WORKBENCH_TOOL_NAMES = ("workbench.status",)


def _res(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def handle_workbench_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "workbench.status":
        return _res(_status.status())
    return None


WORKBENCH_TOOLS = [
    {"name": "workbench.status", "description": "Aggregated Code Workbench map: posture, runtimes, projects, sessions, recent artifacts, known limits, and suggested next actions.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]
