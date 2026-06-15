"""High-level /v1/browser/browse route handler."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.browser.browse_browseract import run_browseract_browse
from arena.browser.browse_cdp import run_cdp_browse
from arena.handler_context import BrowserBrowseHandlerContext


@dataclass(frozen=True)
class BrowserBrowseHandlers:
    browse: object


def make_browser_browse_handlers(ctx: BrowserBrowseHandlerContext) -> BrowserBrowseHandlers:
    async def handle_v1_browser_browse(request: web.Request) -> web.Response:
        """POST /v1/browser/browse — unified browser endpoint with auto backend switching."""
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()

        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

        url = body.get("url")
        if not url:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'url'"}, status=400)

        action = body.get("action", "extract")
        stealth = body.get("stealth", False)
        captcha = body.get("captcha", False)
        wait_for = body.get("wait_for")
        timeout = body.get("timeout", 15)
        width = body.get("width", 1280)
        height = body.get("height", 720)

        if stealth or captcha:
            return await run_browseract_browse(
                ctx,
                action=action,
                url=url,
                wait_for=wait_for,
                timeout=timeout,
                width=width,
                height=height,
            )

        return await run_cdp_browse(
            ctx,
            body=body,
            action=action,
            url=url,
            wait_for=wait_for,
            timeout=timeout,
            width=width,
            height=height,
        )

    return BrowserBrowseHandlers(browse=handle_v1_browser_browse)
