"""Desktop window-action endpoint handler."""
from __future__ import annotations

from aiohttp import web

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
        if action not in {"minimize", "restore", "maximize", "unmaximize", "fullscreen", "unfullscreen", "close", "move", "resize", "move_resize", "center", "move_to_display"}:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "unsupported action"}, status=400)
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
        if action in {"center", "move_to_display"}:
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
        if not result.get("ok") and result.get("status"):
            ctx.record_request(is_error=True, count_request=False)
            status = int(result.pop("status"))
            return ctx.cors_json_response(result, status=status)
        ctx.control_record_agent_action()
        return ctx.cors_json_response(result)

    return handle_v1_desktop_window_action
