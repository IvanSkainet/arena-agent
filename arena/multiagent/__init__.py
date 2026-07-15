"""Multi-agent isolation (v3.86.0).

Public exports are the thin registry helpers from `agents`; nothing
else lives at the package level. Handlers stay in `handlers_agents`
because they depend on aiohttp / the AdminHandlerContext.
"""
from __future__ import annotations

from arena.multiagent.agents import (
    AgentRecord,
    AgentRegistry,
    create,
    get,
    list_agents,
    looks_like_agent_token,
    note_request,
    record_audit,
    resolve_token,
    revoke,
    snapshot,
)

__all__ = [
    "AgentRecord",
    "AgentRegistry",
    "create",
    "get",
    "list_agents",
    "looks_like_agent_token",
    "note_request",
    "record_audit",
    "resolve_token",
    "revoke",
    "snapshot",
]
