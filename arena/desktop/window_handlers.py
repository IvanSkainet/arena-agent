"""Desktop window listing/focus endpoint handlers."""
from __future__ import annotations

import os
import shlex
import shutil

from aiohttp import web

from arena.handler_context import DesktopHandlerContext


def make_desktop_window_handlers(ctx: DesktopHandlerContext):
    async def handle_v1_desktop_windows(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        env = ctx.detect_desktop_env()
        display_env = f'DISPLAY={os.environ.get("DISPLAY", ":0")}'
        attempts = []
        kwin = await ctx.kwin_windows_via_script()
        if kwin and kwin.get("ok"):
            return ctx.cors_json_response({**kwin, "tool": kwin.get("backend", "kwin_script"), "attempts": attempts})
        if kwin:
            attempts.append({"tool": "kwin_script", "ok": False, "error": kwin.get("error")})
        if shutil.which("wmctrl"):
            result = await ctx.desktop_exec(f'{display_env} wmctrl -l -p -G 2>/dev/null', timeout=5)
            attempts.append({"tool": "wmctrl", "ok": result.get("ok"), "stderr": result.get("stderr", "")[:200]})
            if result.get("ok") and result.get("stdout", "").strip():
                windows = []
                for line in result["stdout"].strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split(None, 8)
                    if len(parts) >= 8:
                        windows.append({"id": parts[0], "desktop": parts[1], "pid": parts[2], "geometry": {"x": parts[3], "y": parts[4], "width": parts[5], "height": parts[6]}, "host": parts[7], "title": parts[8] if len(parts) >= 9 else ""})
                return ctx.cors_json_response({"ok": True, "count": len(windows), "windows": windows, "tool": "wmctrl", "attempts": attempts})
        if env.get("has_xdotool"):
            result = await ctx.desktop_exec(f'{display_env} xdotool search --onlyvisible --name "" 2>/dev/null', timeout=5)
            attempts.append({"tool": "xdotool", "ok": result.get("ok"), "stderr": result.get("stderr", "")[:200]})
            if result.get("ok") and result.get("stdout", "").strip():
                windows = []
                for wid in result["stdout"].strip().split("\n")[:50]:
                    wid_q = shlex.quote(wid)
                    geom = await ctx.desktop_exec(f'{display_env} xdotool getwindowgeometry {wid_q} 2>/dev/null', timeout=3)
                    name = await ctx.desktop_exec(f'{display_env} xdotool getwindowname {wid_q} 2>/dev/null', timeout=3)
                    pid = await ctx.desktop_exec(f'{display_env} xdotool getwindowpid {wid_q} 2>/dev/null', timeout=3)
                    windows.append({"id": wid, "title": name.get("stdout", "").strip() if name.get("ok") else "", "pid": pid.get("stdout", "").strip() if pid.get("ok") else None, "geometry": geom.get("stdout", "").strip() if geom.get("ok") else ""})
                return ctx.cors_json_response({"ok": True, "count": len(windows), "windows": windows, "tool": "xdotool", "attempts": attempts})
        return ctx.cors_json_response({"ok": True, "count": 0, "windows": [], "tool": "none", "attempts": attempts})

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
        title_contains = body.get("title")
        if not window_id and not title_contains:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'id' or 'title' parameter"}, status=400)
        result = await ctx.focus_window(
            window_id=window_id,
            title_contains=title_contains,
            verify=body.get("verify", True),
            verify_timeout_ms=body.get("timeout_ms", 1500),
            desktop_exec=ctx.desktop_exec,
            detect_env=ctx.detect_desktop_env,
            get_active_window=ctx.get_active_window,
        )
        if not result.get("ok") and result.get("status"):
            ctx.record_request(is_error=True, count_request=False)
            status = int(result.pop("status"))
            return ctx.cors_json_response(result, status=status)
        ctx.control_record_agent_action()
        return ctx.cors_json_response(result)

    return handle_v1_desktop_windows, handle_v1_desktop_active_window, handle_v1_desktop_focus
