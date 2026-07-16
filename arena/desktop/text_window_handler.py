"""Desktop OCR-to-window target endpoint handler."""
from __future__ import annotations

from aiohttp import web

from arena.desktop.text_window_target import resolve_text_window_target
from arena.handler_context import DesktopHandlerContext
from arena.handler_helpers import authed, err_json



def make_desktop_text_window_handler(ctx: DesktopHandlerContext):
    @authed(ctx)
    async def handle_v1_desktop_resolve_text_target(request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        result = await resolve_text_window_target(
            query=str(body.get("query", "") or ""),
            display=str(body.get("display", "") or ""),
            window_title=str(body.get("title", "") or ""),
            class_contains=str(body.get("class", "") or ""),
            desktop_file=str(body.get("desktop_file", "") or ""),
            resource_name=str(body.get("resource_name", "") or ""),
            pid=int(body["pid"]) if body.get("pid") is not None else None,
            scale=body.get("scale"),
            max_width=body.get("max_width"),
            quality=int(body.get("quality", 80) or 80),
            min_confidence=int(body.get("min_confidence", 40) or 40),
            psm=int(body.get("psm", 11) or 11),
            max_results=int(body.get("max_results", 20) or 20),
            prefer_active_window=bool(body.get("prefer_active_window", True)),
            within_active_window=bool(body.get("within_active_window", False)),
            crop_active_window=bool(body.get("crop_active_window", True)),
            require_active_title=str(body.get("require_active_title", "") or ""),
            max_window_candidates=int(body.get("max_window_candidates", 5) or 5),
            capture_screenshot=ctx.capture_screenshot,
            desktop_exec=ctx.desktop_exec,
            detect_env=ctx.detect_desktop_env,
            get_active_window=ctx.get_active_window,
            kwin_windows_via_script=ctx.kwin_windows_via_script,
            ocr_desktop=ctx.ocr_desktop,
            audit_fn=ctx.audit,
        )
        if not result.get("ok") and result.get("status"):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response(result, status=int(result.pop("status")))
        return ctx.cors_json_response(result)

    return handle_v1_desktop_resolve_text_target
