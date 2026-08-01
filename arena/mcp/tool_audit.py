"""MCP tools for enhanced audit trail (v4.151.0)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.observability.audit_enhanced import (
    classify_action,
    digest,
    export_audit,
    is_external,
    score_risk,
)

AUDIT_TOOL_NAMES = (
    "audit.classify",
    "audit.digest",
    "audit.export",
)


def _audit_path_from_ctx(ctx) -> Path:
    """Resolve the audit.jsonl path from the bridge context."""
    import os
    home = Path(os.environ.get("ARENA_AGENT_HOME", str(Path.home() / "arena-bridge")))
    return home / "audit.jsonl"


def handle_audit_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "audit.classify":
        tool_name = str(args.get("tool") or args.get("tool_name") or "")
        if not tool_name:
            return text_content(json.dumps({"ok": False, "error": "tool name is required"}, ensure_ascii=False))
        return text_content(json.dumps({
            "ok": True,
            "tool": tool_name,
            "category": classify_action(tool_name),
            "risk": score_risk(tool_name),
            "external": is_external(tool_name),
        }, ensure_ascii=False))

    if name == "audit.digest":
        minutes = int(args.get("minutes", 60) or 60)
        limit = int(args.get("limit", 500) or 500)
        path = _audit_path_from_ctx(ctx)
        result = digest(path, minutes=minutes, limit=limit)
        return text_content(json.dumps(result, ensure_ascii=False))

    if name == "audit.export":
        lines = int(args.get("lines", 200) or 200)
        fmt = str(args.get("format", "json") or "json")
        path = _audit_path_from_ctx(ctx)
        result = export_audit(path, lines=lines, format=fmt)
        return text_content(json.dumps(result, ensure_ascii=False))

    return None


AUDIT_TOOLS = [
    {"name": "audit.classify", "description": "Classify a tool name by action category (read/write/execute/network/external/destructive), risk level (low/medium/high/critical), and external flag.", "inputSchema": {"type": "object", "properties": {"tool": {"type": "string"}, "tool_name": {"type": "string"}}, "additionalProperties": False}},
    {"name": "audit.digest", "description": "Summarise recent audit events: counts grouped by risk level, category, external flag, and list of recent high-risk actions.", "inputSchema": {"type": "object", "properties": {"minutes": {"type": "integer", "default": 60}, "limit": {"type": "integer", "default": 500}}, "additionalProperties": False}},
    {"name": "audit.export", "description": "Export recent audit events with enrichment (action classification, risk, external flag) as JSON or Markdown.", "inputSchema": {"type": "object", "properties": {"lines": {"type": "integer", "default": 200}, "format": {"type": "string", "enum": ["json", "markdown"], "default": "json"}}, "additionalProperties": False}},
]


__all__ = ["AUDIT_TOOLS", "handle_audit_tool"]
