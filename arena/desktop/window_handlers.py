"""Desktop window listing and focus endpoint handlers."""
from __future__ import annotations

from aiohttp import web

from arena.desktop.window_catalog import list_desktop_windows, window_candidates
from arena.handler_context import DesktopHandlerContext



def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}



def make_desktop_window_handlers(ctx: DesktopHandlerContext):
    async def handle_v1_desktop_windows(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        result = await list_desktop_windows(
            desktop_exec=ctx.desktop_exec,
            detect_env=ctx.detect_desktop_env,
            kwin_windows_via_script=ctx.kwin_windows_via_script,
        )
        windows = window_candidates(
            list(result.get("windows") or []),
            title=request.query.get("title", ""),
            class_contains=request.query.get("class", ""),
            desktop_file=request.query.get("desktop_file", ""),
            resource_name=request.query.get("resource_name", ""),
            pid=int(request.query["pid"]) if request.query.get("pid", "").isdigit() else None,
            display=request.query.get("display", ""),
            active_only=_truthy(request.query.get("active_only")),
        )
        payload = {
            **result,
            "count": len(windows),
            "all_count": result.get("count", len(result.get("windows") or [])),
            "windows": windows,
            "filters": {k: v for k, v in {
                "title": request.query.get("title", ""),
                "class": request.query.get("class", ""),
                "desktop_file": request.query.get("desktop_file", ""),
                "resource_name": request.query.get("resource_name", ""),
                "pid": request.query.get("pid", ""),
                "display": request.query.get("display", ""),
                "active_only": _truthy(request.query.get("active_only")),
            }.items() if v not in ("", False, None)},
        }
        if not _truthy(request.query.get("include_displays")):
            payload.pop("displays", None)
        return ctx.cors_json_response(payload)

    async def handle_v1_desktop_active_window(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        active = await ctx.get_active_window()
        if active:
            return ctx.cors_json_response({"ok": True, **active})
        return ctx.cors_json_response({"ok": True, "id": None, "title": None, "backend": "none", "message": "Could not determine active window"})

    async def handle_v1_desktop_focus(request: web.Request) -> web.Response:
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

        window_id = body.get("id")
        title_contains = str(body.get("title", "") or "")
        class_contains = str(body.get("class", "") or "")
        desktop_file = str(body.get("desktop_file", "") or "")
        resource_name = str(body.get("resource_name", "") or "")
        display_name = str(body.get("display", "") or "")
        pid = body.get("pid")
        dry_run = bool(body.get("dry_run", False))

        target_title = ""
        candidates = []
        if not window_id or class_contains or desktop_file or resource_name or display_name or pid is not None or dry_run:
            result = await list_desktop_windows(
                desktop_exec=ctx.desktop_exec,
                detect_env=ctx.detect_desktop_env,
                kwin_windows_via_script=ctx.kwin_windows_via_script,
            )
            candidates = window_candidates(
                list(result.get("windows") or []),
                title=title_contains,
                class_contains=class_contains,
                desktop_file=desktop_file,
                resource_name=resource_name,
                pid=int(pid) if pid is not None else None,
                display=display_name,
                active_only=False,
            )
            if not window_id and candidates:
                chosen = candidates[0]
                window_id = chosen.get("id")
                target_title = chosen.get("title", "")

        if not window_id and not title_contains:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'id', 'title', or other window filters"}, status=400)
        if not window_id:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "window_not_found", "candidates": candidates[: int(body.get("max_candidates", 5) or 5)]}, status=404)
        if dry_run:
            return ctx.cors_json_response({
                "ok": True,
                "resolved": True,
                "target_id": window_id,
                "target_title": target_title,
                "candidates": candidates[: int(body.get("max_candidates", 5) or 5)],
                "dry_run": True,
            })
        result = await ctx.focus_window(
            window_id=window_id,
            title_contains=title_contains,
            target_title=target_title,
            verify=body.get("verify", True),
            verify_timeout_ms=body.get("timeout_ms", 1500),
            desktop_exec=ctx.desktop_exec,
            detect_env=ctx.detect_desktop_env,
            get_active_window=ctx.get_active_window,
            kwin_focus_window=ctx.kwin_focus_window,
        )
        if candidates:
            result["candidates"] = candidates[: int(body.get("max_candidates", 5) or 5)]
        if not result.get("ok") and result.get("status"):
            ctx.record_request(is_error=True, count_request=False)
            status = int(result.pop("status"))
            return ctx.cors_json_response(result, status=status)
        ctx.control_record_agent_action()
        return ctx.cors_json_response(result)

    return handle_v1_desktop_windows, handle_v1_desktop_active_window, handle_v1_desktop_focus
