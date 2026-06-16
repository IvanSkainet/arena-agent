"""Public bridge endpoints: index, health and OpenAPI docs."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import PublicHandlerContext
from arena.public.endpoints import PUBLIC_ENDPOINTS
from arena.public.openapi import build_openapi_spec


@dataclass(frozen=True)
class PublicHandlers:
    index: object
    health: object
    api_docs: object


def make_public_handlers(ctx: PublicHandlerContext) -> PublicHandlers:
    async def handle_index(request: web.Request) -> web.Response:
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

    async def handle_health(request: web.Request) -> web.Response:
        try:
            ctx.record_request()
            return ctx.cors_json_response({
                "ok": True,
                "service": "arena-unified-bridge",
                "version": ctx.version,
                "uptime_seconds": round(ctx.now() - ctx.metrics["start_time"], 1),
            })
        except Exception:
            return ctx.cors_json_response({"ok": False, "service": "arena-unified-bridge"}, status=500)

    async def handle_api_docs(request: web.Request) -> web.Response:
        """GET /api-docs — OpenAPI 3.0 specification for all bridge endpoints."""
        return ctx.cors_json_response(build_openapi_spec(ctx))

    return PublicHandlers(index=handle_index, health=handle_health, api_docs=handle_api_docs)


__all__ = ["PUBLIC_ENDPOINTS", "PublicHandlers", "make_public_handlers"]
