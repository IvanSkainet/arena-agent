"""MCP tools for Code Workbench runtime management."""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.workbench import runtimes


def _res(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def handle_runtime_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name in {"runtime.probe", "runtime.list"}:
        return _res(runtimes.probe())
    if name == "runtime.install":
        runtime = str(args.get("runtime") or "").strip().lower()
        if not runtime:
            return _res({"ok": False, "error": "missing runtime"})
        try:
            return _res(runtimes.install(runtime, str(args.get("version") or "") or None))
        except Exception as e:
            return _res({"ok": False, "runtime": runtime, "error": str(e)})
    return None


RUNTIME_TOOLS = [
    {"name": "runtime.probe", "description": "Probe host and Arena-managed language runtimes (python/node/go/rust/java) with versions and diagnostics.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "runtime.list", "description": "Alias for runtime.probe.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "runtime.install", "description": "Install an Arena-managed runtime with SHA verification. v4.108.0 supports Go portable archives from go.dev.",
     "inputSchema": {"type": "object", "properties": {"runtime": {"type": "string", "enum": ["go"]}, "version": {"type": "string", "description": "Optional Go version, e.g. 1.26.5 or go1.26.5"}}, "required": ["runtime"], "additionalProperties": False}},
]
