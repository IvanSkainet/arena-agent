"""MCP tools for persisted Code Workbench run artifacts."""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.workbench import artifacts

ARTIFACT_TOOL_NAMES = ("code_run.info", "code_artifact.read")


def _res(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def handle_code_artifact_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    try:
        if name == "code_run.info":
            return _res(artifacts.run_info(str(args.get("run_id") or "")))
        if name == "code_artifact.read":
            return _res(artifacts.read_artifact(str(args.get("run_id") or ""), str(args.get("path") or ""), max_bytes=int(args.get("max_bytes", 128 * 1024))))
    except Exception as e:
        return _res({"ok": False, "error": str(e)})
    return None


ARTIFACT_TOOLS = [
    {"name": "code_run.info", "description": "Return metadata and artifact manifest for a persisted Code Workbench run.", "inputSchema": {"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"], "additionalProperties": False}},
    {"name": "code_artifact.read", "description": "Read a persisted Code Workbench artifact by run_id and relative artifact path.", "inputSchema": {"type": "object", "properties": {"run_id": {"type": "string"}, "path": {"type": "string"}, "max_bytes": {"type": "integer", "default": 131072}}, "required": ["run_id", "path"], "additionalProperties": False}},
]
