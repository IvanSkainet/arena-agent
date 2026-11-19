"""Public bridge endpoints: index, health and OpenAPI docs."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from aiohttp import web

from arena.handler_context import PublicHandlerContext
from arena.public.endpoints import PUBLIC_ENDPOINTS
from arena.public.openapi import build_openapi_spec


@dataclass(frozen=True)
class PublicHandlers:
    index: Callable[..., Any]
    health: Callable[..., Any]
    api_docs: Callable[..., Any]



async def _handle_index(ctx: PublicHandlerContext, request: web.Request) -> web.Response:
    try:
        ctx.record_request()
        return ctx.cors_json_response({
            "ok": True,
            "service": "arena-unified-bridge",
            "version": ctx.version,
            "endpoints": PUBLIC_ENDPOINTS,
            "auth_required_for_exec": True,
        })
    except Exception as e:
        return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)


async def _handle_health(ctx: PublicHandlerContext, request: web.Request) -> web.Response:
    try:
        ctx.record_request()
        try:
            memory = ctx.memory_status()
        except OSError:
            memory = "error"
        return ctx.cors_json_response({
            "ok": True,
            "service": "arena-unified-bridge",
            "version": ctx.version,
            "memory": memory,
            "status": "degraded" if memory in {"rebuilt", "error"} else "healthy",
            "uptime_seconds": round(ctx.now() - ctx.metrics["start_time"], 1),
        })
    except Exception:
        return ctx.cors_json_response({"ok": False, "service": "arena-unified-bridge"}, status=500)


async def _handle_api_docs(ctx: PublicHandlerContext, request: web.Request) -> web.Response:
    """GET /api-docs — OpenAPI 3.0 specification for all bridge endpoints."""
    return ctx.cors_json_response(build_openapi_spec(ctx))


def _bind_handler(ctx: PublicHandlerContext, handler: Callable[..., Any]) -> Callable[..., Any]:
    async def bound(request: web.Request) -> web.Response:
        return await handler(ctx, request)

    return bound


def make_public_handlers(ctx: PublicHandlerContext) -> PublicHandlers:
    return PublicHandlers(
        index=_bind_handler(ctx, _handle_index),
        health=_bind_handler(ctx, _handle_health),
        api_docs=_bind_handler(ctx, _handle_api_docs))


__all__ = ["PUBLIC_ENDPOINTS", "PublicHandlers", "make_public_handlers"]
