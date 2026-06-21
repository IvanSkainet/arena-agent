"""Desktop window listing and focus endpoint handlers."""
from __future__ import annotations

from aiohttp import web

from arena.desktop.text_window_target import resolve_text_window_target
from arena.desktop.window_catalog import list_desktop_windows, resolve_window_target, window_candidates
from arena.handler_context import DesktopHandlerContext



def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}



def make_desktop_window_handlers(ctx: DesktopHandlerContext):
    async def handle_v1_desktop_windows(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        result = await list_desktop_windows(desktop_exec=ctx.desktop_exec, detect_env=ctx.detect_desktop_env, kwin_windows_via_script=ctx.kwin_windows_via_script)
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
            "filters": {k: v for k, v in {"title": request.query.get("title", ""), "class": request.query.get("class", ""), "desktop_file": request.query.get("desktop_file", ""), "resource_name": request.query.get("resource_name", ""), "pid": request.query.get("pid", ""), "display": request.query.get("display", ""), "active_only": _truthy(request.query.get("active_only"))}.items() if v not in ("", False, None)},
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
        query = str(body.get("query", "") or "")
        title_contains = str(body.get("title", "") or "")
        class_contains = str(body.get("class", "") or "")
        desktop_file = str(body.get("desktop_file", "") or "")
        resource_name = str(body.get("resource_name", "") or "")
        display_name = str(body.get("display", "") or "")
        pid = body.get("pid")
        dry_run = bool(body.get("dry_run", False))

        text_target = None
        if query:
            text_target = await resolve_text_window_target(
                query=query,
                display=display_name,
                window_title=title_contains,
                class_contains=class_contains,
                desktop_file=desktop_file,
                resource_name=resource_name,
                pid=int(pid) if pid is not None else None,
                scale=body.get("scale"),
                max_width=body.get("max_width"),
                quality=int(body.get("quality", 80) or 80),
                min_confidence=int(body.get("min_confidence", 40) or 40),
                psm=int(body.get("psm", 11) or 11),
                max_results=int(body.get("max_results", 20) or 20),
                prefer_active_window=bool(body.get("prefer_active_window", True)),
                within_active_window=bool(body.get("within_active_window", False)),
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
            target = text_target.get("target_window") or {}
            window_id = target.get("id") or target.get("internal_id") or window_id
            title_contains = title_contains or str(target.get("title", "") or "")

        if not window_id and not title_contains and not class_contains and not desktop_file and not resource_name and not display_name and pid is None:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'id', 'title', 'query', or other window filters"}, status=400)
        resolved = await resolve_window_target(
            window_id=window_id,
            title=title_contains,
            class_contains=class_contains,
            desktop_file=desktop_file,
            resource_name=resource_name,
            pid=int(pid) if pid is not None else None,
            display=display_name,
            max_candidates=int(body.get("max_candidates", 5) or 5),
            desktop_exec=ctx.desktop_exec,
            detect_env=ctx.detect_desktop_env,
            kwin_windows_via_script=ctx.kwin_windows_via_script,
        )
        target = resolved.get("target")
        candidates = resolved.get("candidates", [])
        if not target:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "window_not_found", "candidates": candidates}, status=404)
        if dry_run:
            payload = {"ok": True, "resolved": True, "target_id": target.get("id"), "target_title": target.get("title", ""), "target": target, "candidates": candidates, "dry_run": True}
            if text_target:
                payload["text_target"] = text_target
            return ctx.cors_json_response(payload)
        result = await ctx.focus_window(window_id=target.get("id"), title_contains=title_contains, target_title=str(target.get("title", "") or ""), verify=body.get("verify", True), verify_timeout_ms=body.get("timeout_ms", 1500), desktop_exec=ctx.desktop_exec, detect_env=ctx.detect_desktop_env, get_active_window=ctx.get_active_window, kwin_focus_window=ctx.kwin_focus_window)
        result["candidates"] = candidates
        result["target"] = target
        if text_target:
            result["text_target"] = text_target
        if not result.get("ok") and result.get("status"):
            ctx.record_request(is_error=True, count_request=False)
            status = int(result.pop("status"))
            return ctx.cors_json_response(result, status=status)
        ctx.control_record_agent_action()
        return ctx.cors_json_response(result)

    return handle_v1_desktop_windows, handle_v1_desktop_active_window, handle_v1_desktop_focus
