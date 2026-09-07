"""Desktop OCR-to-window target endpoint handler."""
from __future__ import annotations

from aiohttp import web

from arena.desktop.availability import failure_response, is_refusal
from arena.desktop.text_window_target import resolve_text_window_target
from arena.handler_context import DesktopHandlerContext
from arena.handler_helpers import authed, body_int, json_object_body
from arena.handler_params import body_float


def make_desktop_text_window_handler(ctx: DesktopHandlerContext):
    @authed(ctx)
    async def handle_v1_desktop_resolve_text_target(request: web.Request) -> web.Response:
        body = await json_object_body(request)
        result = await resolve_text_window_target(
            query=str(body.get("query", "") or ""),
            display=str(body.get("display", "") or ""),
            window_title=str(body.get("title", "") or ""),
            class_contains=str(body.get("class", "") or ""),
            desktop_file=str(body.get("desktop_file", "") or ""),
            resource_name=str(body.get("resource_name", "") or ""),
            pid=body_int(body, "pid", default=None),
            scale=body_float(body, "scale", default=None),
            max_width=body_int(body, "max_width", default=None),
            quality=body_int(body, "quality", default=80),
            min_confidence=body_int(body, "min_confidence", default=40),
            psm=body_int(body, "psm", default=11),
            max_results=body_int(body, "max_results", default=20),
            prefer_active_window=bool(body.get("prefer_active_window", True)),
            within_active_window=bool(body.get("within_active_window", False)),
            crop_active_window=bool(body.get("crop_active_window", True)),
            require_active_title=str(body.get("require_active_title", "") or ""),
            max_window_candidates=body_int(body, "max_window_candidates", default=5),
            capture_screenshot=ctx.capture_screenshot,
            desktop_exec=ctx.desktop_exec,
            detect_env=ctx.detect_desktop_env,
            get_active_window=ctx.get_active_window,
            kwin_windows_via_script=ctx.kwin_windows_via_script,
            ocr_desktop=ctx.ocr_desktop,
            audit_fn=ctx.audit,
        )
        if is_refusal(result):
            # The `unavailable` half is new: this endpoint answered 200 with
            # `ok: false` when tesseract was missing -- worse than the 500 the
            # others gave, because a caller checking the status code alone
            # read it as success (#260).
            return failure_response(ctx, result)
        return ctx.cors_json_response(result)

    return handle_v1_desktop_resolve_text_target
