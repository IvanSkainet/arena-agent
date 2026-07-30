"""MCP tools for whole-ship status/preflight."""
from __future__ import annotations

import importlib
import json
from typing import Any

from arena.mcp.tool_utils import text_content

_ship_status = importlib.import_module("arena.ship.status")
_linux_flight = importlib.import_module("arena.ship.linux_flight")

SHIP_TOOL_NAMES = ("ship.status", "ship.preflight", "ship.linux_flight_check")


def _res(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def handle_ship_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "ship.status":
        return _res(_ship_status.status())
    if name == "ship.preflight":
        return _res(_ship_status.preflight())
    if name == "ship.linux_flight_check":
        return _res(_linux_flight.status())
    return None


SHIP_TOOLS = [
    {"name": "ship.status", "description": "Whole-ship map: bridge, posture, transports, MCP/desktop, browser/CDP/BrowserAct, mobile/ADB, Workbench, known issues, next actions.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "ship.preflight", "description": "Read-only preflight summary before real scenarios/releases: fail/warn checks plus suggested repairs.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "ship.linux_flight_check", "description": "Read-only Linux/CachyOS flight check: systemd user service, systemd-run, KDE/Wayland hints, Tailscale/Funnel, ADB/mobile, browser, runtimes and next actions.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]
