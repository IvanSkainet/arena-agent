"""MCP basic/exec tools."""
from __future__ import annotations

import json
import os
import platform
from typing import Any

from arena.mcp.tool_utils import text_content


def handle_exec_tool(name: str, args: dict[str, Any], *, ctx, run_sd) -> dict[str, Any] | None:
    # v4.75.0: bare names (ping / echo / exec) removed.
    # The v4.69.0 deprecation window has expired. The
    # dispatcher now accepts only the namespaced exec.*
    # form. Chat-extension adapters that still send the
    # bare form will get a clean ``None`` return (the
    # dispatcher doesn't recognise the name) and the
    # bridge will report a no-such-tool error.
    if name == "exec.ping":
        return text_content("pong")
    if name == "exec.echo":
        return text_content(str(args.get("text", "")))
    if name != "exec.exec":
        return None

    cmd = args.get("cmd", "")
    if not cmd:
        return {"isError": True, "content": [{"type": "text", "text": "ERROR: missing 'cmd' argument"}]}
    block = ctx.blocked_reason(cmd)
    if block:
        return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: {block}"}]}
    profile = os.environ.get("ARENA_PROFILE", "owner-shell")
    if profile == "cautious":
        fw = ctx.first_word(cmd)
        if ctx.cautious_allow and fw not in ctx.cautious_allow and fw.rstrip(".exe") not in ctx.cautious_allow:
            return {"isError": True, "content": [{"type": "text", "text": f"BLOCKED: command '{fw}' not in allowlist"}]}
    if platform.system() == "Windows":
        rc, out, err = run_sd(["cmd", "/c", cmd], timeout=args.get("timeout", 60))
    else:
        rc, out, err = run_sd(["bash", "-lc", cmd], timeout=args.get("timeout", 60))
    return text_content(json.dumps({"exit": rc, "stdout": out[-15000:], "stderr": err[-5000:]}, ensure_ascii=False))
