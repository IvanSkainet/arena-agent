"""Desktop screenshot endpoint handler."""
from __future__ import annotations

import base64
from urllib.parse import parse_qs

from aiohttp import web

from arena.desktop.displays import get_displays, match_display
from arena.handler_context import DesktopHandlerContext
from arena.handler_helpers import authed, err_json


def make_desktop_screenshot_handler(ctx: DesktopHandlerContext):
    @authed(ctx)
    async def handle_v1_desktop_screenshot(request: web.Request) -> web.Response:
        qs = parse_qs(request.query_string)
        fmt = qs.get("format", ["base64"])[0].lower()

        def _qs_float(name):
            try:
                return float(qs.get(name, [None])[0])
            except (TypeError, ValueError):
                return None

        def _qs_int(name):
            try:
                return int(qs.get(name, [None])[0])
            except (TypeError, ValueError):
                return None

        display_name = qs.get("display", [""])[0].strip()
        crop_region = None
        if display_name:
            displays = await get_displays(desktop_exec=ctx.desktop_exec)
            display = match_display(displays.get("displays", []), display_name)
            if not display:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": f"unknown display: {display_name}", "available_displays": displays.get("displays", [])}, status=404)
            crop_region = display.get("geometry")
        shot = await ctx.capture_screenshot(
            fmt=fmt,
            scale=_qs_float("scale"),
            max_width=_qs_int("max_width"),
            quality=_qs_int("quality") or 80,
            region_x=(crop_region or {}).get("x"),
            region_y=(crop_region or {}).get("y"),
            region_width=(crop_region or {}).get("width"),
            region_height=(crop_region or {}).get("height"),
            desktop_exec=ctx.desktop_exec,
            detect_env=ctx.detect_desktop_env,
            audit_fn=ctx.audit,
        )
        if not shot.get("ok"):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": shot.get("error", "Screenshot failed")}, status=500)
        img_bytes = shot["bytes"]
        out_format = shot["encoding"]
        if fmt == "base64":
            return ctx.cors_json_response({
                "ok": True,
                "format": "base64",
                "encoding": out_format,
                "data": base64.b64encode(img_bytes).decode("ascii"),
                "size_bytes": len(img_bytes),
                "transformed": shot.get("transformed", False),
                "tool": shot.get("tool"),
                "display": display_name or None,
                "crop_region": shot.get("crop_region"),
            })
        content_types = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
        return web.Response(body=img_bytes, content_type=content_types.get(out_format, "image/png"), headers={"Access-Control-Allow-Origin": "*"})

    return handle_v1_desktop_screenshot
