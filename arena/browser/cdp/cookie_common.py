"""Shared helpers for CDP cookie handlers."""
from __future__ import annotations

from typing import Any

from arena.browser.cdp.cookie_manager import ensure_cookie_manager
from arena.handler_context import CdpCookiesHandlerContext


def auth_and_record(ctx: CdpCookiesHandlerContext, request: Any):
    """Apply standard auth/metrics prelude used by cookie routes."""
    response = ctx.require_auth(request)
    if response:
        return response
    ctx.record_request()
    return None


def require_cdp_connected(ctx: CdpCookiesHandlerContext):
    """Return a 400 response when cookie routes are called without CDP."""
    if ctx.cdp_state["connected"]:
        return None
    ctx.record_request(is_error=True, count_request=False)
    return ctx.cors_json_response({"ok": False, "error": "CDP not connected"}, status=400)


async def get_cookie_manager_or_response(ctx: CdpCookiesHandlerContext):
    """Return ``(manager, None)`` or ``(None, response)`` for manager startup errors."""
    cookie_mgr = await ensure_cookie_manager(ctx)
    if cookie_mgr:
        return cookie_mgr, None
    ctx.record_request(is_error=True, count_request=False)
    return None, ctx.cors_json_response(
        {"ok": False, "error": "Failed to start cookie manager"},
        status=500,
    )
