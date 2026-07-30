"""MCP tools for Code Workbench runtime management."""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.workbench import runtime_compat, runtimes


def _res(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def handle_runtime_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name in {"runtime.probe", "runtime.list"}:
        return _res(runtimes.probe())
    if name == "runtime.compat":
        return _res(runtime_compat.build())
    if name == "runtime.install":
        runtime = str(args.get("runtime") or "").strip().lower()
        if not runtime:
            return _res({"ok": False, "error": "missing runtime"})
        try:
            return _res(runtimes.install(runtime, str(args.get("version") or "") or None, sha256=str(args.get("sha256") or "") or None))
        except Exception as e:
            return _res({"ok": False, "runtime": runtime, "error": str(e)})
    return None


RUNTIME_TOOLS = [
    {"name": "runtime.compat", "description": "Machine-readable runtime x sandbox compatibility registry: supported/blocked/incomplete/missing, reasons, suggested posture, and next actions.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "runtime.probe", "description": "Probe host and Arena-managed language runtimes (python/node/go/rust/java) with versions and diagnostics.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "runtime.list", "description": "Alias for runtime.probe.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "runtime.install", "description": "Install an Arena-managed runtime with SHA verification. Supports Go portable archives and Wasmtime releases.",
     "inputSchema": {"type": "object", "properties": {"runtime": {"type": "string", "enum": ["go", "deno", "zig", "wasm", "wasmtime"]}, "version": {"type": "string", "description": "Optional version, e.g. Go 1.26.5/go1.26.5, Deno 2.9.4/v2.9.4, Zig 0.16.0, or Wasmtime 47.0.2/v47.0.2"}, "sha256": {"type": "string", "description": "Optional expected SHA-256 for direct Deno fallback when GitHub API rate limits"}}, "required": ["runtime"], "additionalProperties": False}},
]
