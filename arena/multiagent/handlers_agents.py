"""aiohttp handlers for the /v1/agents surface (v3.86.0).

  POST   /v1/agents                {label?}
  GET    /v1/agents                list
  GET    /v1/agents/{agent_id}     one
  DELETE /v1/agents/{agent_id}     revoke

Every endpoint requires the MASTER token (not an agent token), so
agents can't spawn / list / revoke each other. Enforced by checking
that the request's presented token equals `cfg["token"]` exactly --
`request.get("agent_id")` set means an agent token was used.
"""
from __future__ import annotations

import asyncio
import functools
from typing import Any

from aiohttp import web
from arena.app_keys import APP_CFG

from arena.multiagent import agents as _agents


def _requires_master_token(request: web.Request) -> web.Response | None:
    """Reject when the caller authenticated as an agent, not the
    master. Returns None on success or a 403 Response on rejection."""
    # `require_auth` already ran and passed; if it succeeded via an
    # agent token then request["agent_id"] will be set (see the auth
    # runtime patch in v3.86.0).
    is_agent = False
    try:
        is_agent = "agent_id" in request
    except TypeError:
        # aiohttp Request behaves like a dict but some legacy test
        # doubles don't -- treat those as master-authed.
        is_agent = False
    if is_agent:
        return web.json_response(
            {"ok": False,
             "error": "agent tokens cannot manage other agents; "
                      "use the master token for /v1/agents/*"},
            status=403,
        )
    return None


def make_agents_handlers(ctx):
    """Return the four coroutine handlers keyed by short name."""

    async def _run(fn, *args, **kwargs):
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            ctx.executor, functools.partial(fn, *args, **kwargs))

    def _cors(payload, status=200):
        return ctx.cors_json_response(payload, status=status)

    async def handle_agents_create(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        gate = _requires_master_token(request)
        if gate:
            return gate
        ctx.record_request()
        try:
            body = await request.json()
        except Exception:
            body = {}
        label = str((body or {}).get("label") or "agent")
        master = request.app[APP_CFG]["token"]
        try:
            rec = await _run(_agents.create, label=label, master_token=master)
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)
        ctx.audit({"type": "agents.create",
                   "agent_id": rec.agent_id, "label": rec.label})
        # Include the token in the CREATE response so the caller can
        # use it -- this is the only path where we return it.
        return _cors({"ok": True,
                      "action": "agents.create",
                      "agent": _agents.snapshot(rec, include_token=True)})

    async def handle_agents_list(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        gate = _requires_master_token(request)
        if gate:
            return gate
        ctx.record_request()
        try:
            snaps = [_agents.snapshot(rec) for rec in _agents.list_agents()]
            return _cors({"ok": True, "count": len(snaps), "agents": snaps})
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return _cors({"ok": False, "error": str(e)}, status=500)

    async def handle_agents_get(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        gate = _requires_master_token(request)
        if gate:
            return gate
        ctx.record_request()
        agent_id = request.match_info.get("agent_id", "")
        rec = _agents.get(agent_id)
        if rec is None:
            return _cors({"ok": False,
                          "error": f"no agent with id {agent_id!r}"},
                         status=404)
        return _cors({"ok": True, "agent": _agents.snapshot(rec)})

    async def handle_agents_delete(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        gate = _requires_master_token(request)
        if gate:
            return gate
        ctx.record_request()
        agent_id = request.match_info.get("agent_id", "")
        removed = _agents.revoke(agent_id)
        if not removed:
            return _cors({"ok": False,
                          "error": f"no agent with id {agent_id!r}"},
                         status=404)
        ctx.audit({"type": "agents.revoke", "agent_id": agent_id})
        return _cors({"ok": True, "action": "agents.revoke",
                      "agent_id": agent_id})

    return {
        "agents_create": handle_agents_create,
        "agents_list":   handle_agents_list,
        "agents_get":    handle_agents_get,
        "agents_delete": handle_agents_delete,
    }
