"""MCP planning tool."""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_utils import text_content


def handle_plan_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    if name != "plan.create":
        return None
    goal = str(args.get("goal", "")).strip()
    if not goal:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'goal' argument"}]}
    try:
        result = ctx.build_plan(
            goal=goal,
            context=str(args.get("context", "") or ""),
            constraints=args.get("constraints") or [],
            max_steps=args.get("max_steps", 8),
            memory_profile=args.get("memory_profile"),
        )
    except Exception as e:
        return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {type(e).__name__}: {e}"}]}
    return text_content(json.dumps(result, ensure_ascii=False))
