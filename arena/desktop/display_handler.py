"""Desktop display/output endpoint handler."""
from __future__ import annotations

from aiohttp import web

from arena.desktop.displays import get_displays
from arena.handler_context import DesktopHandlerContext
from arena.handler_helpers import authed, err_json



def make_desktop_display_handler(ctx: DesktopHandlerContext):
    @authed(ctx)
    async def handle_v1_desktop_displays(request: web.Request) -> web.Response:
        result = await get_displays(desktop_exec=ctx.desktop_exec)
        if not result.get("ok"):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response(result, status=500)
        return ctx.cors_json_response(result)

    return handle_v1_desktop_displays
