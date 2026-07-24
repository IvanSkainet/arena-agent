"""MCP basic/exec tools."""
from __future__ import annotations

import json
import os
import platform
import warnings
from typing import Any

from arena.mcp.tool_utils import text_content

# v4.69.0: when a caller still uses the legacy bare form
# (ping / echo / exec / snapshot), the dispatcher emits a
# ``PendingDeprecationWarning`` so the server log surfaces the
# regression. ``PendingDeprecationWarning`` is the right class
# here (not ``DeprecationWarning``) because the bare form is
# still *working* — it is being *soft-warned* ahead of a real
# removal in v4.75.0. The catalogue entry also carries a
# ``deprecationMessage`` field so well-behaved clients can
# render the deprecation in their tool palette.
_BARE_NAME_WARN = {
    "ping": "exec.ping",
    "echo": "exec.echo",
    "exec": "exec.exec",
}


def _warn_bare(name: str) -> None:
    replacement = _BARE_NAME_WARN.get(name)
    if replacement is None:
        return
    warnings.warn(
        f"tool name {name!r} is deprecated as of v4.69.0; use {replacement!r} instead. "
        f"The bare form will be removed in v4.75.0.",
        PendingDeprecationWarning,
        stacklevel=3,
    )


def handle_exec_tool(name: str, args: dict[str, Any], *, ctx, run_sd) -> dict[str, Any] | None:
    # v4.67.0: accept both the legacy bare names and the
    # namespaced exec.* form. The bare names are kept for
    # backward compat with chat-extension adapters that have
    # not been updated yet; new code should call exec.ping /
    # exec.echo / exec.exec. See arena.mcp.tool_registry for
    # the canonical entry definitions.
    #
    # v4.69.0: bare-name calls now emit a PendingDeprecationWarning.
    if name in ("ping", "exec.ping"):
        if name == "ping":
            _warn_bare("ping")
        return text_content("pong")
    if name in ("echo", "exec.echo"):
        if name == "echo":
            _warn_bare("echo")
        return text_content(str(args.get("text", "")))
    if name in ("exec", "exec.exec"):
        if name == "exec":
            _warn_bare("exec")
        # fall through to the actual exec handler below
    else:
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
