"""MCP document.* tools: deterministic text structuring (v4.89.0)."""
from __future__ import annotations

import json
from typing import Any

from arena.document.structure import assess_text_quality, extract_tasks, structure_document
from arena.mcp.tool_utils import text_content


def handle_document_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    text = str(args.get("text", "") or "")
    if name == "document.input_quality":
        sq = args.get("source_quality") if isinstance(args.get("source_quality"), dict) else None
        return text_content(json.dumps(assess_text_quality(text, sq), ensure_ascii=False))
    if name == "document.extract_tasks":
        sq = args.get("source_quality") if isinstance(args.get("source_quality"), dict) else None
        return text_content(json.dumps(extract_tasks(
            text,
            language=str(args.get("language") or "auto"),
            source_quality=sq,
            quality_gate=bool(args.get("quality_gate", True)),
            allow_low_quality=bool(args.get("allow_low_quality", False)),
        ), ensure_ascii=False))
    if name == "document.structure":
        return text_content(json.dumps(structure_document(
            text,
            kind=str(args.get("kind") or "auto"),
            language=str(args.get("language") or "auto"),
        ), ensure_ascii=False))
    return None


__all__ = ["handle_document_tool"]
