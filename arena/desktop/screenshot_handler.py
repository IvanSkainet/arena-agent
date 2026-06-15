"""Desktop screenshot endpoint handler."""
from __future__ import annotations

import base64
from urllib.parse import parse_qs

from aiohttp import web

from arena.handler_context import DesktopHandlerContext


def make_desktop_screenshot_handler(ctx: DesktopHandlerContext):
    async def handle_v1_desktop_screenshot(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
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

        shot = await ctx.capture_screenshot(
            fmt=fmt,
            scale=_qs_float("scale"),
            max_width=_qs_int("max_width"),
            quality=_qs_int("quality") or 80,
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
            })
        content_types = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
        return web.Response(body=img_bytes, content_type=content_types.get(out_format, "image/png"), headers={"Access-Control-Allow-Origin": "*"})

    return handle_v1_desktop_screenshot
