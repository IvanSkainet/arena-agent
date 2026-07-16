"""Handlers for simple non-CDP browser fetch/search endpoints."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import parse_qs

from aiohttp import web

from arena.handler_context import BrowserFetchHandlerContext
from arena.handler_helpers import authed, err_json


@dataclass(frozen=True)
class BrowserFetchHandlers:
    search: object
    read: object
    dump: object
    fetch: object
    head: object


def make_browser_fetch_handlers(ctx: BrowserFetchHandlerContext) -> BrowserFetchHandlers:
    @authed(ctx)
    async def handle_v1_browser_search(request: web.Request) -> web.Response:
        qs = parse_qs(request.query_string)
        query = qs.get("q", [""])[0]
        try:
            n = int(qs.get("n", ["5"])[0])
        except ValueError:
            n = 5
        if not query:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing q parameter"}, status=400)
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(ctx.executor, ctx.browser_search_sync, query, n)
        return ctx.cors_json_response(result)

    def make_url_handler(sync_fn, missing_error: str):
        async def handler(request: web.Request) -> web.Response:
            r = ctx.require_auth(request)
            if r:
                return r
            ctx.record_request()
            qs = parse_qs(request.query_string)
            url = qs.get("url", [""])[0]
            if not url:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": missing_error}, status=400)
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(ctx.executor, sync_fn, url)
                return ctx.cors_json_response(result)
            except Exception as e:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

        return handler

    return BrowserFetchHandlers(
        search=handle_v1_browser_search,
        read=make_url_handler(ctx.browser_read_sync, "missing url parameter"),
        dump=make_url_handler(ctx.browser_dump_sync, "missing url parameter"),
        fetch=make_url_handler(ctx.browser_fetch_sync, "missing url parameter"),
        head=make_url_handler(ctx.browser_head_sync, "missing url parameter"),
    )
