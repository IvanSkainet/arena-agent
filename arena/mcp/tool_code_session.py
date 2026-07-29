"""MCP tools for long-running Code Workbench sessions."""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.workbench import sessions

SESSION_TOOL_NAMES = (
    "code_session.start", "code_session.exec", "code_session.list",
    "code_session.stop", "code_session.stop_all",
)


def _res(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def handle_code_session_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "code_session.start":
        return _res(sessions.start(lang=str(args.get("lang") or "python3"), name=str(args.get("name") or ""),
                                   cwd=args.get("cwd") if isinstance(args.get("cwd"), str) else None,
                                   project=args.get("project") if isinstance(args.get("project"), str) else None,
                                   use_project_deps=bool(args.get("use_project_deps", False))))
    if name == "code_session.exec":
        return _res(sessions.exec_code(str(args.get("session_id") or ""), str(args.get("code") or ""), timeout=float(args.get("timeout", 30))))
    if name == "code_session.list":
        return _res(sessions.list_sessions())
    if name == "code_session.stop":
        return _res(sessions.stop(str(args.get("session_id") or "")))
    if name == "code_session.stop_all":
        return _res(sessions.stop_all())
    return None


SESSION_TOOLS = [
    {"name": "code_session.start", "description": "Start a long-running Python Code Workbench session. MVP requires operator posture sandbox=off.", "inputSchema": {"type": "object", "properties": {"lang": {"type": "string", "default": "python3"}, "name": {"type": "string"}, "cwd": {"type": "string"}, "project": {"type": "string"}, "use_project_deps": {"type": "boolean", "default": False}}, "additionalProperties": False}},
    {"name": "code_session.exec", "description": "Execute Python code in a long-running Code Workbench session, preserving globals between calls.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}, "code": {"type": "string"}, "timeout": {"type": "number", "default": 30}}, "required": ["session_id", "code"], "additionalProperties": False}},
    {"name": "code_session.list", "description": "List live Code Workbench sessions.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "code_session.stop", "description": "Stop one Code Workbench session.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}}, "required": ["session_id"], "additionalProperties": False}},
    {"name": "code_session.stop_all", "description": "Stop all live Code Workbench sessions.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]
