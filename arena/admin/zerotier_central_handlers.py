"""aiohttp handlers for the ZeroTier Central management surface
(v3.96.0). Split out of arena/admin/handlers.py to keep that file
under the 700-line ceiling.

Every handler uses @authed from arena.handler_helpers to enforce
Bearer auth and centrally accounting for stray exceptions, and
err_json for consistent error responses.

Routes (registered from arena.route_registry):
    GET    /v1/zerotier/central/status
    GET    /v1/zerotier/central/networks
    POST   /v1/zerotier/central/networks               body: {name, config?}
    GET    /v1/zerotier/central/networks/{nwid}
    DELETE /v1/zerotier/central/networks/{nwid}
    GET    /v1/zerotier/central/networks/{nwid}/members
    POST   /v1/zerotier/central/networks/{nwid}/members/{node}
                                                       body: {authorized?, name?, ...}
    DELETE /v1/zerotier/central/networks/{nwid}/members/{node}
"""
from __future__ import annotations

import asyncio
import functools
from dataclasses import dataclass

from aiohttp import web

from arena.admin.zerotier_central import (
    central_status,
    create_network,
    delete_member,
    delete_network,
    get_network,
    list_members,
    list_networks,
    update_member,
)
from arena.handler_context import AdminHandlerContext
from arena.handler_helpers import authed, err_json, parse_json_body


@dataclass(frozen=True)
class ZerotierCentralHandlers:
    status: object
    networks_list: object
    networks_create: object
    network_get: object
    network_delete: object
    members_list: object
    member_update: object
    member_delete: object


async def _run(ctx, fn, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(ctx.executor, functools.partial(fn, *args, **kwargs))


def make_zerotier_central_handlers(ctx: AdminHandlerContext) -> ZerotierCentralHandlers:
    @authed(ctx)
    async def handle_status(request: web.Request) -> web.Response:
        """GET /v1/zerotier/central/status — token discovery + probe."""
        result = await _run(ctx, central_status)
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_networks_list(request: web.Request) -> web.Response:
        """GET /v1/zerotier/central/networks — every owned network."""
        result = await _run(ctx, list_networks)
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_networks_create(request: web.Request) -> web.Response:
        """POST /v1/zerotier/central/networks — create + audit.

        Body: {"name": "<required>", "config": {...optional Central schema...}}
        """
        data, jerr = await parse_json_body(request, ctx)
        if jerr is not None:
            return jerr
        name = str(data.get("name") or "").strip()
        if not name:
            return err_json(ctx, "name required", status=400)
        config = data.get("config") if isinstance(data.get("config"), dict) else None
        # `config` accepts the full Central payload — the caller's
        # top-level `config` merges under `payload["config"]` in the
        # central client so operators can pass a subset.
        wrapper = {"config": config} if config else None
        result = await _run(ctx, create_network, name, wrapper)
        ctx.audit({
            "type": "zerotier_central_create_network",
            "name": name,
            "ok": bool(result.get("ok")),
            "network_id": (result.get("network") or {}).get("id"),
            "client": request.remote or "127.0.0.1",
        })
        # 201 on success, mirror central status otherwise so caller
        # sees the auth/upstream failure directly.
        status = 201 if result.get("ok") else int(result.get("status") or 400)
        return ctx.cors_json_response(result, status=status)

    @authed(ctx)
    async def handle_network_get(request: web.Request) -> web.Response:
        """GET /v1/zerotier/central/networks/{nwid} — full detail."""
        nwid = request.match_info.get("nwid", "")
        result = await _run(ctx, get_network, nwid)
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_network_delete(request: web.Request) -> web.Response:
        """DELETE /v1/zerotier/central/networks/{nwid} — permanent."""
        nwid = request.match_info.get("nwid", "")
        result = await _run(ctx, delete_network, nwid)
        ctx.audit({
            "type": "zerotier_central_delete_network",
            "network_id": nwid,
            "ok": bool(result.get("ok")),
            "client": request.remote or "127.0.0.1",
        })
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_members_list(request: web.Request) -> web.Response:
        """GET /v1/zerotier/central/networks/{nwid}/members."""
        nwid = request.match_info.get("nwid", "")
        result = await _run(ctx, list_members, nwid)
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_member_update(request: web.Request) -> web.Response:
        """POST /v1/zerotier/central/networks/{nwid}/members/{node}.

        Body: {authorized?: bool, name?: str, description?: str,
               ip_assignments?: list[str]}
        """
        nwid = request.match_info.get("nwid", "")
        node = request.match_info.get("node", "")
        data, jerr = await parse_json_body(request, ctx)
        if jerr is not None:
            return jerr
        kwargs = {}
        if "authorized" in data:
            kwargs["authorized"] = bool(data["authorized"])
        if isinstance(data.get("name"), str):
            kwargs["name"] = data["name"]
        if isinstance(data.get("description"), str):
            kwargs["description"] = data["description"]
        if isinstance(data.get("ip_assignments"), list):
            kwargs["ip_assignments"] = data["ip_assignments"]
        result = await _run(ctx, update_member, nwid, node, **kwargs)
        ctx.audit({
            "type": "zerotier_central_update_member",
            "network_id": nwid,
            "node_id": node,
            "changes": kwargs,
            "ok": bool(result.get("ok")),
            "client": request.remote or "127.0.0.1",
        })
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_member_delete(request: web.Request) -> web.Response:
        """DELETE /v1/zerotier/central/networks/{nwid}/members/{node}."""
        nwid = request.match_info.get("nwid", "")
        node = request.match_info.get("node", "")
        result = await _run(ctx, delete_member, nwid, node)
        ctx.audit({
            "type": "zerotier_central_delete_member",
            "network_id": nwid,
            "node_id": node,
            "ok": bool(result.get("ok")),
            "client": request.remote or "127.0.0.1",
        })
        return ctx.cors_json_response(result)

    return ZerotierCentralHandlers(
        status=handle_status,
        networks_list=handle_networks_list,
        networks_create=handle_networks_create,
        network_get=handle_network_get,
        network_delete=handle_network_delete,
        members_list=handle_members_list,
        member_update=handle_member_update,
        member_delete=handle_member_delete,
    )
