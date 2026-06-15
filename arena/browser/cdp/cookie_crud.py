"""CRUD handlers for CDP cookies."""
from __future__ import annotations

from urllib.parse import parse_qs

from arena.browser.cdp.cookie_common import (
    auth_and_record,
    get_cookie_manager_or_response,
    require_cdp_connected,
)
from arena.handler_context import CdpCookiesHandlerContext


def make_cdp_cookies_get_handler(ctx: CdpCookiesHandlerContext):
    async def handle_v1_cdp_cookies_get(request):
        """GET /v1/browser/cdp/cookies — Get cookies."""
        response = auth_and_record(ctx, request)
        if response:
            return response
        response = require_cdp_connected(ctx)
        if response:
            return response

        try:
            cookie_mgr, response = await get_cookie_manager_or_response(ctx)
            if response:
                return response

            qs = parse_qs(request.query_string)
            url = qs.get("url", [None])[0]
            domain = qs.get("domain", [None])[0]

            if url:
                cookies = await cookie_mgr.get_cookies_for_url(url)
            elif domain:
                all_cookies = await cookie_mgr.get_all_cookies()
                cookies = [c for c in all_cookies if domain in c.get("domain", "")]
            else:
                cookies = await cookie_mgr.get_all_cookies()

            return ctx.cors_json_response({
                "ok": True,
                "cookies": cookies,
                "count": len(cookies),
            })
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return handle_v1_cdp_cookies_get


def make_cdp_cookies_set_handler(ctx: CdpCookiesHandlerContext):
    async def handle_v1_cdp_cookies_set(request):
        """POST /v1/browser/cdp/cookies — Set a cookie."""
        response = auth_and_record(ctx, request)
        if response:
            return response
        response = require_cdp_connected(ctx)
        if response:
            return response

        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

        name = body.get("name")
        value = body.get("value")
        if not name or value is None:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'name' or 'value'"}, status=400)

        try:
            cookie_mgr, response = await get_cookie_manager_or_response(ctx)
            if response:
                return response

            success = await cookie_mgr.set_cookie(
                name=name,
                value=value,
                domain=body.get("domain", ""),
                path=body.get("path", "/"),
                secure=body.get("secure", False),
                http_only=body.get("http_only", False),
                same_site=body.get("same_site", ""),
                expires=body.get("expires"),
            )

            return ctx.cors_json_response({
                "ok": success,
                "name": name,
                "domain": body.get("domain", ""),
            })
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return handle_v1_cdp_cookies_set


def make_cdp_cookies_delete_handler(ctx: CdpCookiesHandlerContext):
    async def handle_v1_cdp_cookies_delete(request):
        """DELETE /v1/browser/cdp/cookies — Delete a cookie."""
        response = auth_and_record(ctx, request)
        if response:
            return response
        response = require_cdp_connected(ctx)
        if response:
            return response

        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)

        name = body.get("name")
        if not name:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'name'"}, status=400)

        try:
            cookie_mgr, response = await get_cookie_manager_or_response(ctx)
            if response:
                return response

            await cookie_mgr.delete_cookie(name, domain=body.get("domain", ""))

            return ctx.cors_json_response({
                "ok": True,
                "deleted": name,
            })
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return handle_v1_cdp_cookies_delete


def make_cdp_cookies_clear_handler(ctx: CdpCookiesHandlerContext):
    async def handle_v1_cdp_cookies_clear(request):
        """POST /v1/browser/cdp/cookies/clear — Clear all cookies."""
        response = auth_and_record(ctx, request)
        if response:
            return response
        response = require_cdp_connected(ctx)
        if response:
            return response

        try:
            cookie_mgr, response = await get_cookie_manager_or_response(ctx)
            if response:
                return response

            await cookie_mgr.clear_cookies()

            return ctx.cors_json_response({"ok": True, "message": "All cookies cleared"})
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": str(e)}, status=500)

    return handle_v1_cdp_cookies_clear
