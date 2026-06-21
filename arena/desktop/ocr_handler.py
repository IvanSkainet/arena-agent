"""Desktop OCR endpoint handlers."""
from __future__ import annotations

from dataclasses import dataclass

from aiohttp import web

from arena.handler_context import DesktopHandlerContext


@dataclass(frozen=True)
class DesktopOcrHandlers:
    ocr: object
    find_text: object



def make_desktop_ocr_handlers(ctx: DesktopHandlerContext) -> DesktopOcrHandlers:
    async def handle_v1_desktop_ocr(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            data = await request.json() if request.can_read_body else {}
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        result = await ctx.ocr_desktop(
            query=str(data.get("query", "") or ""),
            scale=data.get("scale"),
            max_width=data.get("max_width"),
            quality=int(data.get("quality", 80) or 80),
            min_confidence=int(data.get("min_confidence", 40) or 40),
            psm=int(data.get("psm", 11) or 11),
            max_results=int(data.get("max_results", 20) or 20),
            capture_screenshot=ctx.capture_screenshot,
            desktop_exec=ctx.desktop_exec,
            detect_env=ctx.detect_desktop_env,
            audit_fn=ctx.audit,
        )
        if not result.get("ok"):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response(result, status=500)
        return ctx.cors_json_response(result)

    async def handle_v1_desktop_find_text(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        try:
            data = await request.json()
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        query = str(data.get("query", "") or "").strip()
        if not query:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing query"}, status=400)
        result = await ctx.ocr_desktop(
            query=query,
            scale=data.get("scale"),
            max_width=data.get("max_width"),
            quality=int(data.get("quality", 80) or 80),
            min_confidence=int(data.get("min_confidence", 40) or 40),
            psm=int(data.get("psm", 11) or 11),
            max_results=int(data.get("max_results", 20) or 20),
            capture_screenshot=ctx.capture_screenshot,
            desktop_exec=ctx.desktop_exec,
            detect_env=ctx.detect_desktop_env,
            audit_fn=ctx.audit,
        )
        if not result.get("ok"):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response(result, status=500)
        if not result.get("matches"):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({**result, "error": f"no matches for query: {query}"}, status=404)
        return ctx.cors_json_response(result)

    return DesktopOcrHandlers(ocr=handle_v1_desktop_ocr, find_text=handle_v1_desktop_find_text)
