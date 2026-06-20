"""MCP file watcher tool."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from arena.files.sandbox import resolve_home_path
from arena.mcp.tool_utils import text_content


def handle_watch_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    if name != "watch.files":
        return None
    action = str(args.get("action", "list") or "list").strip().lower()
    if action == "list":
        return text_content(json.dumps(ctx.file_watch_list_sync(), ensure_ascii=False))
    if action == "remove":
        watch_id = str(args.get("id", "")).strip()
        if not watch_id:
            return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'id' argument"}]}
        return text_content(json.dumps(ctx.file_watch_remove_sync(watch_id), ensure_ascii=False))
    if action == "add":
        target = str(args.get("path", "")).strip()
        if not target:
            return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'path' argument"}]}
        cfg = ctx.app_config()
        root = Path(cfg.get("root") or Path.home())
        resolved, err, status = resolve_home_path(target, root=root, home=root if root.is_absolute() else Path.home())
        if err:
            return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {err} ({status})"}]}
        result = ctx.file_watch_add_sync(
            path=str(resolved),
            root=root,
            recursive=bool(args.get("recursive", True)),
            patterns=args.get("patterns") or [],
            label=str(args.get("label", "") or ""),
            created_at=ctx.utc_now(),
        )
        return text_content(json.dumps(result, ensure_ascii=False))
    return {"isError": True, "content": [{"type": "text", "text": f"ERROR: unknown action '{action}'"}]}
