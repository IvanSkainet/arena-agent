"""Desktop OCR-to-action workflow endpoint handler."""
from __future__ import annotations

from aiohttp import web

from arena.desktop.availability import failure_response, is_refusal
from arena.desktop.text_action import run_text_action
from arena.handler_context import DesktopHandlerContext
from arena.handler_helpers import body_int, controlled, parse_json_body


def make_desktop_text_action_handler(ctx: DesktopHandlerContext):
    @controlled(ctx)
    async def handle_v1_desktop_text_action(request: web.Request) -> web.Response:
        body, jerr = await parse_json_body(request, ctx)
        if jerr is not None:
            ctx.record_request(is_error=True, count_request=False)
            return jerr
        assert body is not None  # the guard above already proved this
        action = str(body.get("action", "resolve") or "resolve")
        result = await run_text_action(
            action=action,
            query=str(body.get("query", "") or ""),
            display=str(body.get("display", "") or ""),
            target_display=str(body.get("target_display", "") or ""),
            title=str(body.get("title", "") or ""),
            class_contains=str(body.get("class", "") or ""),
            desktop_file=str(body.get("desktop_file", "") or ""),
            resource_name=str(body.get("resource_name", "") or ""),
            pid=body_int(body, "pid", default=None),
            scale=body.get("scale"),
            max_width=body.get("max_width"),
            quality=body_int(body, "quality", default=80),
            min_confidence=body_int(body, "min_confidence", default=40),
            psm=body_int(body, "psm", default=11),
            max_results=body_int(body, "max_results", default=20),
            prefer_active_window=bool(body.get("prefer_active_window", True)),
            within_active_window=bool(body.get("within_active_window", False)),
            crop_active_window=bool(body.get("crop_active_window", True)),
            require_active_title=str(body.get("require_active_title", "") or ""),
            max_window_candidates=body_int(body, "max_window_candidates", default=5),
            target_position=str(body.get("target_position", "center") or "center"),
            offset_x=body_int(body, "offset_x", default=0),
            offset_y=body_int(body, "offset_y", default=0),
            button=str(body.get("button", "left") or "left"),
            double=bool(body.get("double", False)),
            activate=bool(body.get("activate", True)),
            dry_run=bool(body.get("dry_run", False)),
            verify=bool(body.get("verify", True)),
            timeout_ms=body_int(body, "timeout_ms", default=1000),
            capture_screenshot=ctx.capture_screenshot,
            desktop_exec=ctx.desktop_exec,
            detect_env=ctx.detect_desktop_env,
            get_active_window=ctx.get_active_window,
            kwin_windows_via_script=ctx.kwin_windows_via_script,
            ocr_desktop=ctx.ocr_desktop,
            focus_window=ctx.focus_window,
            kwin_focus_window=ctx.kwin_focus_window,
            audit_fn=ctx.audit,
        )
        if is_refusal(result):
            # `unavailable` as well as `status`: OCR reached through this
            # endpoint used to answer 200 with `ok: false` when tesseract was
            # missing, and a click without ydotool a bare 500 (#260).
            return failure_response(ctx, result)
        if result.get("ok") and not body.get("dry_run", False):
            ctx.control_record_agent_action()
        return ctx.cors_json_response(result)

    return handle_v1_desktop_text_action
