"""MCP memory tools."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any

from arena.mcp.tool_utils import text_content


def handle_memory_tool(name: str, args: dict[str, Any], *, ctx, run_local) -> dict[str, Any] | None:
    if name == "mem.set":
        key = args.get("key", "")
        value = args.get("value", "")
        if not key:
            return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'key' argument"}]}
        tags = args.get("tags") or []
        entry = {"key": key, "value": value, "tags": tags, "timestamp": datetime.now(timezone.utc).isoformat()}
        ctx.write_fact(entry)
        ctx.audit({"type": "memory_set", "key": key, "via": "mcp"})
        return text_content(json.dumps({"ok": True, "fact": entry}, ensure_ascii=False))

    if name == "mem.get":
        q = args.get("query", args.get("q", ""))
        facts = ctx.load_facts()
        if q:
            q_low = q.lower()
            facts = [f for f in facts if q_low in json.dumps(f, ensure_ascii=False).lower()]
        return text_content(json.dumps({"ok": True, "count": len(facts), "facts": facts[-50:]}, ensure_ascii=False))

    if name == "memory.recall":
        cmd_args = [sys.executable, os.path.join(ctx.bin_dir, "memory_recall.py"), "recall",
                    args.get("query", ""), "--top", str(args.get("top", 5))]
        rc, out, err = run_local(cmd_args, timeout=15)
        return text_content(out or err)

    if name == "memory.digest":
        rc, out, err = run_local([sys.executable, os.path.join(ctx.bin_dir, "memory_recall.py"), "digest"], timeout=15)
        return text_content(out or err)

    return None
