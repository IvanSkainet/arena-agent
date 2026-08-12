"""MCP tools for persisted Code Workbench run artifacts."""
from __future__ import annotations

import json
from typing import Any

from arena.foundry import tools as _foundry
from arena.mcp.tool_utils import text_content
from arena.workbench import artifacts

ARTIFACT_TOOL_NAMES = ("code_run.info", "code_run.promote_tool", "code_artifact.read")


def _res(payload: dict[str, Any]) -> dict[str, Any]:
    return text_content(json.dumps(payload, ensure_ascii=False))


def handle_code_artifact_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    try:
        if name == "code_run.info":
            return _res(artifacts.run_info(str(args.get("run_id") or "")))
        if name == "code_run.promote_tool":
            raw_schema = args.get("input_schema") if isinstance(args.get("input_schema"), dict) else (args.get("inputSchema") if isinstance(args.get("inputSchema"), dict) else {})
            input_schema: dict[str, Any] = dict(raw_schema) if isinstance(raw_schema, dict) else {}
            raw_run = args.get("run")
            run_dict: dict[str, Any] = dict(raw_run) if isinstance(raw_run, dict) else {}
            raw_tests = args.get("tests")
            tests_list: list[dict[str, Any]] = [dict(t) for t in raw_tests] if isinstance(raw_tests, list) else []
            return _res(_foundry.promote_run(
                str(args.get("run_id") or ""),
                project=str(args.get("project") or args.get("name") or ""),
                tool_name=str(args.get("tool_name") or args.get("tool") or ""),
                description=str(args.get("description") or ""),
                input_schema=input_schema,
                run=run_dict,
                tests=tests_list,
                manifest_path=str(args.get("manifest_path") or _foundry.DEFAULT_MANIFEST),
                publish_tool=bool(args.get("publish", True)),
                overwrite_manifest=bool(args.get("overwrite_manifest", False)),
            ))
        if name == "code_artifact.read":
            return _res(artifacts.read_artifact(str(args.get("run_id") or ""), str(args.get("path") or ""), max_bytes=int(args.get("max_bytes", 128 * 1024))))
    except Exception as e:
        return _res({"ok": False, "error": str(e)})
    return None


ARTIFACT_TOOLS = [
    {"name": "code_run.info", "description": "Return metadata and artifact manifest for a persisted Code Workbench run.", "inputSchema": {"type": "object", "properties": {"run_id": {"type": "string"}}, "required": ["run_id"], "additionalProperties": False}},
    {"name": "code_run.promote_tool", "description": "Promote a persisted Code Workbench run as provenance for a project-backed Foundry manifest and optionally publish custom.<name>.", "inputSchema": {"type": "object", "properties": {"run_id": {"type": "string"}, "project": {"type": "string"}, "name": {"type": "string"}, "tool_name": {"type": "string"}, "description": {"type": "string"}, "input_schema": {"type": "object"}, "inputSchema": {"type": "object"}, "run": {"type": "object"}, "tests": {"type": "array"}, "manifest_path": {"type": "string", "default": ".arena-tool.json"}, "publish": {"type": "boolean", "default": True}, "overwrite_manifest": {"type": "boolean", "default": False}}, "required": ["run_id", "project", "tool_name", "description", "run", "tests"], "additionalProperties": False}},
    {"name": "code_artifact.read", "description": "Read a persisted Code Workbench artifact by run_id and relative artifact path.", "inputSchema": {"type": "object", "properties": {"run_id": {"type": "string"}, "path": {"type": "string"}, "max_bytes": {"type": "integer", "default": 131072}}, "required": ["run_id", "path"], "additionalProperties": False}},
]
