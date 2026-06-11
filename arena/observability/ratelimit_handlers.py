"""Handlers for rate-limit configuration/statistics endpoints."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import RateLimitHandlerContext


@dataclass(frozen=True)
class RateLimitHandlers:
    ratelimit: object


def make_rate_limit_handlers(ctx: RateLimitHandlerContext) -> RateLimitHandlers:
    async def handle_v1_ratelimit(request: web.Request) -> web.Response:
        """GET /v1/ratelimit — Rate limit configuration and stats.
        POST /v1/ratelimit — Update rate limit configuration.
        """
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        if request.method == "POST":
            try:
                data = await request.json()
                ctx.update_rate_limit_config(data)
                ctx.log_info("[RateLimitv2] Configuration updated")
            except Exception as e:
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=400)
        return ctx.cors_json_response(ctx.rate_limit_stats())

    return RateLimitHandlers(ratelimit=handle_v1_ratelimit)
