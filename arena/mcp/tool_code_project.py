"""MCP tools for persistent Code Workbench projects."""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.workbench import projects

PROJECT_TOOL_NAMES = (
    "code_project.create", "code_project.list", "code_project.write",
    "code_project.read", "code_project.remove", "code_project.run",
)


def _res(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def handle_code_project_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    try:
        if name == "code_project.create":
            return _res(projects.create(str(args.get("name") or ""), args.get("files") or [], overwrite=bool(args.get("overwrite", False))))
        if name == "code_project.list":
            return _res(projects.list_projects())
        if name == "code_project.write":
            return _res(projects.write(str(args.get("name") or ""), str(args.get("path") or ""), str(args.get("content") or ""), encoding=str(args.get("encoding") or "utf-8")))
        if name == "code_project.read":
            return _res(projects.read(str(args.get("name") or ""), str(args.get("path") or ""), max_bytes=int(args.get("max_bytes", 100000))))
        if name == "code_project.remove":
            return _res(projects.remove(str(args.get("name") or "")))
        if name == "code_project.run":
            argv = args.get("argv") or []
            artifacts = args.get("artifacts") or []
            if not isinstance(argv, list) or not isinstance(artifacts, list):
                return _res({"ok": False, "error": "argv and artifacts must be arrays"})
            return _res(projects.run(str(args.get("name") or ""), lang=str(args.get("lang") or "python3"),
                                     entry=str(args.get("entry") or ""), argv=[str(a) for a in argv],
                                     stdin=args.get("stdin") if isinstance(args.get("stdin"), str) else None,
                                     artifacts=[str(a) for a in artifacts],
                                     deps=args.get("deps") if isinstance(args.get("deps"), dict) else None,
                                     timeout=int(args.get("timeout")) if args.get("timeout") else None))
    except Exception as e:
        return _res({"ok": False, "error": str(e)})
    return None


PROJECT_TOOLS = [
    {"name": "code_project.create", "description": "Create a persistent Code Workbench project under ARENA_AGENT_HOME/code-projects.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "files": {"type": "array"}, "overwrite": {"type": "boolean", "default": False}}, "required": ["name"], "additionalProperties": False}},
    {"name": "code_project.list", "description": "List persistent Code Workbench projects.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "code_project.write", "description": "Write a file in a Code Workbench project.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "path": {"type": "string"}, "content": {"type": "string"}, "encoding": {"type": "string", "enum": ["utf-8", "base64"], "default": "utf-8"}}, "required": ["name", "path", "content"], "additionalProperties": False}},
    {"name": "code_project.read", "description": "Read a file from a Code Workbench project.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "path": {"type": "string"}, "max_bytes": {"type": "integer", "default": 100000}}, "required": ["name", "path"], "additionalProperties": False}},
    {"name": "code_project.remove", "description": "Remove a Code Workbench project.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"], "additionalProperties": False}},
    {"name": "code_project.run", "description": "Run a persistent Code Workbench project through the operator-owned code.run posture fence.", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "lang": {"type": "string", "default": "python3"}, "entry": {"type": "string"}, "argv": {"type": "array", "items": {"type": "string"}}, "stdin": {"type": "string"}, "artifacts": {"type": "array", "items": {"type": "string"}}, "deps": {"type": "object"}, "timeout": {"type": "integer"}}, "required": ["name", "entry"], "additionalProperties": False}},
]
