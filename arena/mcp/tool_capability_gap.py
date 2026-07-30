"""MCP tools for persistent capability gap tracking."""
from __future__ import annotations

import json
from typing import Any

from arena import capability_gaps
from arena.mcp.tool_utils import text_content


def handle_capability_gap_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    if name == "capability_gap.record":
        return text_content(json.dumps(capability_gaps.record(
            title=str(args.get("title") or ""),
            evidence=args.get("evidence"),
            suggested_tool=str(args.get("suggested_tool") or ""),
            severity=str(args.get("severity") or "medium"),
            scenario=str(args.get("scenario") or ""),
            status=str(args.get("status") or "open"),
            tags=args.get("tags"),
        ), ensure_ascii=False))
    if name == "capability_gap.list":
        return text_content(json.dumps(capability_gaps.list_gaps(
            status=str(args.get("status") or ""),
            limit=int(args.get("limit", 50) or 50),
        ), ensure_ascii=False))
    if name == "capability_gap.resolve":
        return text_content(json.dumps(capability_gaps.resolve(
            gap_id=str(args.get("id") or args.get("gap_id") or ""),
            resolution=str(args.get("resolution") or ""),
            status=str(args.get("status") or "resolved"),
        ), ensure_ascii=False))
    return None


CAPABILITY_GAP_TOOLS = [
    {"name": "capability_gap.record", "description": "Record a missing bridge/agent capability discovered during a real scenario, with evidence and suggested tool/runtime/scenario fix.", "inputSchema": {"type": "object", "properties": {"title": {"type": "string"}, "evidence": {}, "suggested_tool": {"type": "string"}, "severity": {"type": "string", "default": "medium"}, "scenario": {"type": "string"}, "status": {"type": "string", "default": "open"}, "tags": {"type": "array", "items": {}}}, "required": ["title"], "additionalProperties": False}},
    {"name": "capability_gap.list", "description": "List recorded open/resolved capability gaps.", "inputSchema": {"type": "object", "properties": {"status": {"type": "string"}, "limit": {"type": "integer", "default": 50}}, "additionalProperties": False}},
    {"name": "capability_gap.resolve", "description": "Mark a capability gap as resolved/closed with a resolution note.", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}, "gap_id": {"type": "string"}, "resolution": {"type": "string"}, "status": {"type": "string", "default": "resolved"}}, "additionalProperties": False}},
]


__all__ = ["CAPABILITY_GAP_TOOLS", "handle_capability_gap_tool"]
