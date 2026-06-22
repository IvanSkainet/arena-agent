"""Desktop OCR-to-action workflow endpoint handler."""
from __future__ import annotations

from aiohttp import web

from arena.desktop.text_action import run_text_action
from arena.handler_context import DesktopHandlerContext



def make_desktop_text_action_handler(ctx: DesktopHandlerContext):
    async def handle_v1_desktop_text_action(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctrl_err = ctx.control_check()
        if ctrl_err:
            return ctx.cors_json_response(ctrl_err, status=403)
        ctx.record_request()
        try:
            body = await request.json()
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
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
            target_position=str(body.get("target_position", "center") or "center"),
            offset_x=int(body.get("offset_x", 0) or 0),
            offset_y=int(body.get("offset_y", 0) or 0),
            button=str(body.get("button", "left") or "left"),
            double=bool(body.get("double", False)),
            activate=bool(body.get("activate", True)),
            dry_run=bool(body.get("dry_run", False)),
            verify=bool(body.get("verify", True)),
            timeout_ms=int(body.get("timeout_ms", 1000) or 1000),
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
        if not result.get("ok") and result.get("status"):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response(result, status=int(result.pop("status")))
        if result.get("ok") and not body.get("dry_run", False):
            ctx.control_record_agent_action()
        return ctx.cors_json_response(result)

    return handle_v1_desktop_text_action
