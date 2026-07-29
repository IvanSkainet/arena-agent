"""MCP tools for long-running Code Workbench sessions."""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.workbench import sessions

SESSION_TOOL_NAMES = (
    "code_session.start", "code_session.exec", "code_session.list",
    "code_session.stop", "code_session.stop_all", "code_session.sweep", "code_session.write", "code_session.read",
    "code_session.files", "code_session.artifacts",
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
        artifacts = args.get("artifacts") if isinstance(args.get("artifacts"), list) else None
        return _res(sessions.exec_code(str(args.get("session_id") or ""), str(args.get("code") or ""), timeout=float(args.get("timeout", 30)), artifacts=[str(a) for a in artifacts] if artifacts else None))
    if name == "code_session.write":
        return _res(sessions.write_file(str(args.get("session_id") or ""), str(args.get("path") or ""), str(args.get("content") or ""), encoding=str(args.get("encoding") or "utf-8")))
    if name == "code_session.read":
        return _res(sessions.read_file(str(args.get("session_id") or ""), str(args.get("path") or ""), max_bytes=int(args.get("max_bytes", 100000))))
    if name == "code_session.files":
        return _res(sessions.list_files(str(args.get("session_id") or ""), max_files=int(args.get("max_files", 200))))
    if name == "code_session.artifacts":
        patterns = args.get("artifacts") or args.get("patterns") or []
        if not isinstance(patterns, list):
            return _res({"ok": False, "error": "artifacts/patterns must be an array"})
        return _res(sessions.session_artifacts(str(args.get("session_id") or ""), [str(p) for p in patterns]))
    if name == "code_session.list":
        return _res(sessions.list_sessions())
    if name == "code_session.stop":
        return _res(sessions.stop(str(args.get("session_id") or ""), kill_after=float(args.get("kill_after", 5))))
    if name == "code_session.sweep":
        return _res(sessions.sweep(
            max_idle_sec=float(args["max_idle_sec"]) if args.get("max_idle_sec") is not None else None,
            max_age_sec=float(args["max_age_sec"]) if args.get("max_age_sec") is not None else None,
            dry_run=bool(args.get("dry_run", False)),
        ))
    if name == "code_session.stop_all":
        return _res(sessions.stop_all())
    return None


SESSION_TOOLS = [
    {"name": "code_session.start", "description": "Start a long-running Python Code Workbench session. MVP requires operator posture sandbox=off.", "inputSchema": {"type": "object", "properties": {"lang": {"type": "string", "default": "python3"}, "name": {"type": "string"}, "cwd": {"type": "string"}, "project": {"type": "string"}, "use_project_deps": {"type": "boolean", "default": False}}, "additionalProperties": False}},
    {"name": "code_session.exec", "description": "Execute Python code in a long-running Code Workbench session, preserving globals between calls. Optionally persist declared artifacts from the session cwd.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}, "code": {"type": "string"}, "timeout": {"type": "number", "default": 30}, "artifacts": {"type": "array", "items": {"type": "string"}}}, "required": ["session_id", "code"], "additionalProperties": False}},
    {"name": "code_session.write", "description": "Write a file into a live Code Workbench session cwd.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}, "path": {"type": "string"}, "content": {"type": "string"}, "encoding": {"type": "string", "enum": ["utf-8", "base64"], "default": "utf-8"}}, "required": ["session_id", "path", "content"], "additionalProperties": False}},
    {"name": "code_session.read", "description": "Read a file from a live Code Workbench session cwd.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}, "path": {"type": "string"}, "max_bytes": {"type": "integer", "default": 100000}}, "required": ["session_id", "path"], "additionalProperties": False}},
    {"name": "code_session.files", "description": "List files in a live Code Workbench session cwd.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}, "max_files": {"type": "integer", "default": 200}}, "required": ["session_id"], "additionalProperties": False}},
    {"name": "code_session.artifacts", "description": "Persist artifacts from a live Code Workbench session cwd into the Code Workbench run artifact store.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}, "artifacts": {"type": "array", "items": {"type": "string"}}, "patterns": {"type": "array", "items": {"type": "string"}}}, "required": ["session_id"], "additionalProperties": False}},
    {"name": "code_session.list", "description": "List live Code Workbench sessions.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "code_session.stop", "description": "Stop one Code Workbench session with terminate-then-kill escalation and returncode/stderr tail diagnostics.", "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}, "kill_after": {"type": "number", "default": 5}}, "required": ["session_id"], "additionalProperties": False}},
    {"name": "code_session.sweep", "description": "Dry-run or stop stale Code Workbench sessions by idle/age threshold; dead sessions are removed first.", "inputSchema": {"type": "object", "properties": {"max_idle_sec": {"type": "number"}, "max_age_sec": {"type": "number"}, "dry_run": {"type": "boolean", "default": False}}, "additionalProperties": False}},
    {"name": "code_session.stop_all", "description": "Stop all live Code Workbench sessions.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
]
