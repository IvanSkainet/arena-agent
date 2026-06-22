"""Desktop window-action endpoint handler."""
from __future__ import annotations

from aiohttp import web

from arena.desktop.text_window_target import resolve_text_window_target
from arena.desktop.window_action import perform_window_action
from arena.desktop.window_action_plans import plan_window_action_geometry
from arena.desktop.window_catalog import resolve_window_target
from arena.handler_context import DesktopHandlerContext



def make_desktop_window_action_handler(ctx: DesktopHandlerContext):
    async def handle_v1_desktop_window_action(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctrl_err = ctx.control_check()
        if ctrl_err:
            return ctx.cors_json_response(ctrl_err, status=403)
        ctx.record_request()
        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
        action = str(body.get("action", "") or "").strip().lower()
        if action not in {"minimize", "restore", "maximize", "unmaximize", "fullscreen", "unfullscreen", "close", "move", "resize", "move_resize", "center", "move_to_display", "snap_left", "snap_right", "snap_top", "snap_bottom", "snap_top_left", "snap_top_right", "snap_bottom_left", "snap_bottom_right"}:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "unsupported action"}, status=400)
        query = str(body.get("query", "") or "")
        text_target = None
        if query:
            text_target = await resolve_text_window_target(
                query=query,
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
                max_window_candidates=int(body.get("max_candidates", 5) or 5),
                capture_screenshot=ctx.capture_screenshot,
                desktop_exec=ctx.desktop_exec,
                detect_env=ctx.detect_desktop_env,
                get_active_window=ctx.get_active_window,
                kwin_windows_via_script=ctx.kwin_windows_via_script,
                ocr_desktop=ctx.ocr_desktop,
                audit_fn=ctx.audit,
            )
            if not text_target.get("ok"):
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response(text_target, status=int(text_target.pop("status", 404)))
            body["id"] = (text_target.get("target_window") or {}).get("id") or body.get("id")
            body["title"] = body.get("title") or (text_target.get("target_window") or {}).get("title")
        resolved = await resolve_window_target(
            window_id=body.get("id"),
            title=str(body.get("title", "") or ""),
            class_contains=str(body.get("class", "") or ""),
            desktop_file=str(body.get("desktop_file", "") or ""),
            resource_name=str(body.get("resource_name", "") or ""),
            pid=int(body["pid"]) if body.get("pid") is not None else None,
            display=str(body.get("display", "") or ""),
            max_candidates=int(body.get("max_candidates", 5) or 5),
            desktop_exec=ctx.desktop_exec,
            detect_env=ctx.detect_desktop_env,
            kwin_windows_via_script=ctx.kwin_windows_via_script,
        )
        target = resolved.get("target")
        if not target:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "window_not_found", "candidates": resolved.get("candidates", [])}, status=404)
        preview = None
        if action in {"center", "move_to_display", "snap_left", "snap_right", "snap_top", "snap_bottom", "snap_top_left", "snap_top_right", "snap_bottom_left", "snap_bottom_right"}:
            preview = plan_window_action_geometry(action, before=target, displays=list((resolved.get("listing") or {}).get("displays") or []), target_display=str(body.get("target_display", "") or ""))
            if not preview.get("ok"):
                ctx.record_request(is_error=True, count_request=False)
                return ctx.cors_json_response(preview, status=int(preview.get("status", 400)))
        if body.get("dry_run", False):
            payload = {"ok": True, "resolved": True, "action": action, "target": target, "candidates": resolved.get("candidates", []), "dry_run": True}
            if preview:
                payload["planned_geometry"] = {"x": preview["x"], "y": preview["y"], "width": preview["width"], "height": preview["height"]}
                payload["source_display"] = preview.get("source_display")
                payload["target_display"] = preview.get("target_display")
            if text_target:
                payload["text_target"] = text_target
            return ctx.cors_json_response(payload)
        result = await perform_window_action(
            action,
            target_id=str(target.get("id") or target.get("internal_id") or ""),
            title_contains=str(body.get("title", "") or ""),
            target_title=str(target.get("title", "") or ""),
            x=body.get("x"),
            y=body.get("y"),
            width=body.get("width"),
            height=body.get("height"),
            target_display=str(body.get("target_display", "") or ""),
            verify=body.get("verify", True),
            verify_timeout_ms=body.get("timeout_ms", 1000),
            desktop_exec=ctx.desktop_exec,
            detect_env=ctx.detect_desktop_env,
            kwin_windows_via_script=ctx.kwin_windows_via_script,
        )
        result["target"] = target
        result["candidates"] = resolved.get("candidates", [])
        if text_target:
            result["text_target"] = text_target
        if not result.get("ok") and result.get("status"):
            ctx.record_request(is_error=True, count_request=False)
            status = int(result.pop("status"))
            return ctx.cors_json_response(result, status=status)
        ctx.control_record_agent_action()
        return ctx.cors_json_response(result)

    return handle_v1_desktop_window_action
