"""MCP memory tools."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from arena.mcp.tool_utils import text_content
from arena.memory.profiles import (
    DEFAULT_MEMORY_PROFILE,
    normalize_memory_profile,
    normalize_memory_profile_filter,
    validate_memory_profile,
)

# v4.78.0: bare 'mem.set' / 'mem.get' names removed
# (the v4.71.0 deprecation window has expired). The
# dispatcher now accepts only the namespaced
# memory.* form. Clients that still send the bare
# form will get a clean ``None`` return (the
# dispatcher doesn't recognise the name) and the
# bridge will report a no-such-tool error.


def _retitle_digest(text: str, title: str) -> str:
    lines = (text or "").splitlines()
    if len(lines) >= 3 and lines[0].startswith("# Memory Digest"):
        return title + "\n\n" + "\n".join(lines[2:])
    return title + "\n\n" + (text or "")


def handle_memory_tool(name: str, args: dict[str, Any], *, ctx, run_local) -> dict[str, Any] | None:
    if name == "memory.recall":
        profile_err = validate_memory_profile(args.get("profile"), allow_all=True)
        if profile_err:
            return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {profile_err}"}]}
        profile = normalize_memory_profile_filter(args.get("profile"))
        result = ctx.recall_sync(args.get("query", ""), int(args.get("top", 5)), profile)
        result["profile"] = profile if profile is not None else "all"
        return text_content(json.dumps(result, ensure_ascii=False))

    if name == "memory.digest":
        profile_err = validate_memory_profile(args.get("profile"), allow_all=True)
        if profile_err:
            return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {profile_err}"}]}
        profile = normalize_memory_profile_filter(args.get("profile"))
        result = ctx.recall_digest_sync(profile)
        if profile not in (None, DEFAULT_MEMORY_PROFILE):
            result["digest"] = _retitle_digest(result.get("digest", ""), f"# Memory Digest ({profile})")
        elif profile is None:
            result["digest"] = _retitle_digest(result.get("digest", ""), "# Memory Digest (all profiles)")
        return text_content(result.get("digest", json.dumps(result, ensure_ascii=False)))

    return None
