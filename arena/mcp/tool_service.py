"""MCP tools for bridge service/autostart diagnostics."""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.service import autostart_doctor


def _res(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def handle_service_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "service.autostart_status":
        return _res(autostart_doctor.status())
    if name == "service.autostart_repair":
        return _res(autostart_doctor.repair())
    return None


SERVICE_TOOLS = [
    {"name": "service.autostart_status", "description": "Diagnose bridge service autostart setup cross-platform (Windows Scheduled Task/NSSM, Linux systemd --user, macOS launchd).", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "service.autostart_repair", "description": "Repair bridge autostart setup on supported platforms (Windows per-user ONLOGON Scheduled Task; Linux systemd --user enable --now).", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]
