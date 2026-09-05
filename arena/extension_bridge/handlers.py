"""HTTP handlers for browser chat extension execution."""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from arena.handler_context import ExtensionBridgeHandlerContext
from arena.handler_helpers import BadRequest, authed, bad_request_refusal, json_object_body


@dataclass(frozen=True)
class ExtensionBridgeHandlers:
    policies: Callable[..., Any]
    preview: Callable[..., Any]
    execute: Callable[..., Any]
    instructions: Callable[..., Any]



def make_extension_bridge_handlers(ctx: ExtensionBridgeHandlerContext) -> ExtensionBridgeHandlers:
    async def _post_json(sync_fn, request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        # _post_json rolls its own auth instead of wearing @authed, so there
        # is no wrapper above it to turn a BadRequest into the 400.
        try:
            data = await json_object_body(request)
        except BadRequest as e:
            return bad_request_refusal(ctx, e)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, sync_fn, data)
        status = int(result.pop("status", 200 if result.get("ok") else 400))
        return ctx.cors_json_response(result, status=status)

    @authed(ctx)
    async def handle_policies(request: web.Request) -> web.Response:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.policies_sync, {})
        return ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_instructions(request: web.Request) -> web.Response:
        # v4.51.1: accept optional `category` query param so the
        # popup can request a full tool catalog scoped to a topic
        # (safe / mission / fs / etc.) without changing the
        # base instructions API contract.
        data = {
            "format": request.query.get("format", "arena"),
            "style": request.query.get("style", "full"),
            "category": request.query.get("category", ""),
        }
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.instructions_sync, data)
        return ctx.cors_json_response(result)

    async def handle_preview(request: web.Request) -> web.Response:
        return await _post_json(ctx.preview_sync, request)

    async def handle_execute(request: web.Request) -> web.Response:
        return await _post_json(ctx.execute_sync, request)

    return ExtensionBridgeHandlers(policies=handle_policies, preview=handle_preview, execute=handle_execute, instructions=handle_instructions)


__all__ = ["ExtensionBridgeHandlers", "make_extension_bridge_handlers"]

