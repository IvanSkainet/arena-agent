"""MCP session runtime helpers."""
from __future__ import annotations

import secrets
import time
from typing import Any

MCP_SESSIONS: dict[str, dict[str, Any]] = {}  # session_id -> {created, queue}
MCP_SESSION_MAX_AGE_MS = 3600_000  # 1 hour — stale sessions auto-cleaned


def now_ms() -> int:
    return int(time.time() * 1000)


def sid() -> str:
    return secrets.token_urlsafe(18)


def cleanup_mcp_sessions(sessions: dict[str, dict[str, Any]] | None = None) -> int:
    """Remove MCP sessions older than MCP_SESSION_MAX_AGE_MS. Returns count removed."""
    target = MCP_SESSIONS if sessions is None else sessions
    now = now_ms()
    stale = [session_id for session_id, sess in target.items()
             if now - sess.get("created", 0) > MCP_SESSION_MAX_AGE_MS]
    for session_id in stale:
        target.pop(session_id, None)
    return len(stale)
