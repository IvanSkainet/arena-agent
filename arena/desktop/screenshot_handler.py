"""Desktop screenshot endpoint handler."""
from __future__ import annotations

import base64
from urllib.parse import parse_qs

from aiohttp import web

from arena.desktop.displays import get_displays, match_display
from arena.handler_context import DesktopHandlerContext
from arena.handler_helpers import authed, query_int


def make_desktop_screenshot_handler(ctx: DesktopHandlerContext):
    @authed(ctx)
    async def handle_v1_desktop_screenshot(request: web.Request) -> web.Response:
        qs = parse_qs(request.query_string)
        fmt = qs.get("format", ["raw"])[0].lower()

        def _qs_float(name: str) -> float | None:
            raw = qs.get(name, [None])[0]
            if raw is None or raw == "":
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None

        display_name = qs.get("display", [""])[0].strip()
        crop_region = None
        region_keys = {"region_x", "region_y", "region_width", "region_height"}
        region_requested = any((qs.get(key, [None])[0] not in (None, "")) for key in region_keys)
        if display_name and region_requested:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "use either 'display' or explicit region_* crop parameters, not both"}, status=400)
        if display_name:
            displays = await get_displays(desktop_exec=ctx.desktop_exec)
            display = match_display(displays.get("displays", []), display_name)
            if not display:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": f"unknown display: {display_name}", "available_displays": displays.get("displays", [])}, status=404)
            crop_region = display.get("geometry")
        elif region_requested:
            crop_region = {
                "x": query_int(request, "region_x", default=None),
                "y": query_int(request, "region_y", default=None),
                "width": query_int(request, "region_width", default=None),
                "height": query_int(request, "region_height", default=None),
            }
            if None in crop_region.values() or int(crop_region.get("width") or 0) <= 0 or int(crop_region.get("height") or 0) <= 0:
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response({"ok": False, "error": "explicit screenshot crop requires integer region_x, region_y, region_width > 0, and region_height > 0"}, status=400)
        shot = await ctx.capture_screenshot(
            fmt=fmt,
            scale=_qs_float("scale"),
            max_width=query_int(request, "max_width", default=None),
            # `or 80` is kept, not tidied away: quality=0 has always meant
            # "use the default", and this fix changes rejected values only.
            quality=query_int(request, "quality", default=80) or 80,
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
