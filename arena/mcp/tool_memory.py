"""MCP memory tools."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from arena.memory.profiles import DEFAULT_MEMORY_PROFILE, normalize_memory_profile, normalize_memory_profile_filter, validate_memory_profile
from arena.mcp.tool_utils import text_content


def _retitle_digest(text: str, title: str) -> str:
    lines = (text or "").splitlines()
    if len(lines) >= 3 and lines[0].startswith("# Memory Digest"):
        return title + "\n\n" + "\n".join(lines[2:])
    return title + "\n\n" + (text or "")


def handle_memory_tool(name: str, args: dict[str, Any], *, ctx, run_local) -> dict[str, Any] | None:
    if name == "mem.set":
        key = args.get("key", "")
        value = args.get("value", "")
        if not key:
            return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'key' argument"}]}
        profile_err = validate_memory_profile(args.get("profile"))
        if profile_err:
            return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {profile_err}"}]}
        profile = normalize_memory_profile(args.get("profile"))
        tags = args.get("tags") or []
        entry = {
            "profile": profile,
            "key": key,
            "value": value,
            "tags": tags,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        ctx.write_fact(entry)
        ctx.audit({"type": "memory_set", "key": key, "profile": profile, "via": "mcp"})
        return text_content(json.dumps({"ok": True, "fact": entry}, ensure_ascii=False))

    if name == "mem.get":
        q = args.get("query", args.get("q", ""))
        profile_err = validate_memory_profile(args.get("profile"), allow_all=True)
        if profile_err:
            return {"isError": True, "content": [{"type": "text", "text": f"ERROR: {profile_err}"}]}
        profile = normalize_memory_profile_filter(args.get("profile"))
        facts = ctx.load_facts(profile)
        if q:
            q_low = q.lower()
            facts = [f for f in facts if q_low in json.dumps(f, ensure_ascii=False).lower()]
        payload = {
            "ok": True,
            "profile": profile if profile is not None else "all",
            "count": len(facts),
            "facts": facts[-50:],
        }
        return text_content(json.dumps(payload, ensure_ascii=False))

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
