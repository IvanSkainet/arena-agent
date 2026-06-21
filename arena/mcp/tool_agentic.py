"""MCP tools for bounded ReAct loops and reflection."""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_utils import text_content


def handle_agentic_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    if name == "react.run":
        goal = str(args.get("goal", "")).strip()
        if not goal:
            return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'goal' argument"}]}
        result = ctx.react_sync(
            goal=goal,
            context=str(args.get("context", "") or ""),
            constraints=args.get("constraints") or [],
            max_iterations=int(args.get("max_iterations", 4) or 4),
            memory_profile=args.get("memory_profile"),
            url=str(args.get("url", "") or ""),
        )
        return text_content(json.dumps(result, ensure_ascii=False))

    if name == "reflect.run":
        result = ctx.reflect_sync(
            goal=str(args.get("goal", "") or ""),
            run=args.get("run") or {},
            notes=str(args.get("notes", "") or ""),
            outcome=str(args.get("outcome", "") or ""),
        )
        return text_content(json.dumps(result, ensure_ascii=False))

    return None
