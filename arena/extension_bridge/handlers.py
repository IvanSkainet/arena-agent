"""HTTP handlers for browser chat extension execution."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import ExtensionBridgeHandlerContext


@dataclass(frozen=True)
class ExtensionBridgeHandlers:
    policies: object
    preview: object
    execute: object
    instructions: object



def make_extension_bridge_handlers(ctx: ExtensionBridgeHandlerContext) -> ExtensionBridgeHandlers:
    async def _post_json(sync_fn, request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            data = await request.json()
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, sync_fn, data)
        status = int(result.pop("status", 200 if result.get("ok") else 400))
        return ctx.cors_json_response(result, status=status)

    async def handle_policies(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.policies_sync, {})
        return ctx.cors_json_response(result)

    async def handle_instructions(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        data = {"format": request.query.get("format", "arena"), "style": request.query.get("style", "full")}
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.instructions_sync, data)
        return ctx.cors_json_response(result)

    async def handle_preview(request: web.Request) -> web.Response:
        return await _post_json(ctx.preview_sync, request)

    async def handle_execute(request: web.Request) -> web.Response:
        return await _post_json(ctx.execute_sync, request)

    return ExtensionBridgeHandlers(policies=handle_policies, preview=handle_preview, execute=handle_execute, instructions=handle_instructions)


__all__ = ["ExtensionBridgeHandlers", "make_extension_bridge_handlers"]
