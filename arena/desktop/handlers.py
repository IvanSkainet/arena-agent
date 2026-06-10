"""Handlers for desktop automation endpoints."""
from __future__ import annotations

import base64
import os
import shlex
import shutil
from dataclasses import dataclass
from urllib.parse import parse_qs

from aiohttp import web

from arena.desktop.input import build_click_command, build_key_command, build_mouse_command, build_type_command
from arena.handler_context import DesktopHandlerContext


@dataclass(frozen=True)
class DesktopHandlers:
    screenshot: object
    click: object
    type: object
    key: object
    mouse: object
    windows: object
    active_window: object
    focus: object


def make_desktop_handlers(ctx: DesktopHandlerContext) -> DesktopHandlers:
    async def handle_v1_desktop_screenshot(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctx.record_request()
        qs = parse_qs(request.query_string)
        fmt = qs.get("format", ["base64"])[0].lower()

        def _qs_float(name):
            try:
                return float(qs.get(name, [None])[0])
            except (TypeError, ValueError):
                return None

        def _qs_int(name):
            try:
                return int(qs.get(name, [None])[0])
            except (TypeError, ValueError):
                return None

        shot = await ctx.capture_screenshot(
            fmt=fmt,
            scale=_qs_float("scale"),
            max_width=_qs_int("max_width"),
            quality=_qs_int("quality") or 80,
            desktop_exec=ctx.desktop_exec,
            detect_env=ctx.detect_desktop_env,
            audit_fn=ctx.audit,
        )
        if not shot.get("ok"):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": shot.get("error", "Screenshot failed")}, status=500)
        img_bytes = shot["bytes"]
        out_format = shot["encoding"]
        if fmt == "base64":
            return ctx.cors_json_response({
                "ok": True,
                "format": "base64",
                "encoding": out_format,
                "data": base64.b64encode(img_bytes).decode("ascii"),
                "size_bytes": len(img_bytes),
                "transformed": shot.get("transformed", False),
                "tool": shot.get("tool"),
            })
        content_types = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}
        return web.Response(body=img_bytes, content_type=content_types.get(out_format, "image/png"), headers={"Access-Control-Allow-Origin": "*"})

    async def _check_required_title(body):
        require_title = body.get("require_active_title")
        if require_title:
            active = await ctx.get_active_window()
            if active and require_title.lower() not in active.get("title", "").lower():
                return ctx.cors_json_response({
                    "ok": False,
                    "error": "input_guard_failed",
                    "message": "Active window does not match required title",
                    "active_window": active,
                    "required_title_contains": require_title,
                }, status=409)
        return None

    async def handle_v1_desktop_click(request: web.Request) -> web.Response:
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
        x = body.get("x")
        y = body.get("y")
        if x is None or y is None:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'x' and/or 'y' coordinates"}, status=400)
        guard = await _check_required_title(body)
        if guard:
            return guard
        ctx.control_record_agent_action()
        env = ctx.detect_desktop_env()
        cmd, tool, err = build_click_command(
            env=env,
            x=int(x),
            y=int(y),
            button=body.get("button", "left"),
            double=body.get("double", False),
            activate=body.get("activate", True),
            has_kdotool=shutil.which("kdotool") is not None,
        )
        if err:
            return ctx.cors_json_response({"ok": False, "error": err}, status=500)
        result = await ctx.desktop_exec(cmd, timeout=10)
        if not result.get("ok"):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"Click failed ({tool}): {result.get('stderr', result.get('error', ''))}"}, status=500)
        return ctx.cors_json_response({"ok": True, "x": int(x), "y": int(y), "button": body.get("button", "left"), "double": body.get("double", False), "tool": tool})

    async def handle_v1_desktop_type(request: web.Request) -> web.Response:
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
        guard = await _check_required_title(body)
        if guard:
            return guard
        ctx.control_record_agent_action()
        text = body.get("text")
        if text is None:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'text' parameter"}, status=400)
        delay = body.get("delay", 50)
        clear = body.get("clear", False)
        ensure_latin = body.get("ensure_latin", True)
        env = ctx.detect_desktop_env()
        layout_switched = False
        if ensure_latin:
            try:
                res = await ctx.desktop_exec("qdbus6 org.kde.keyboard /Layouts setLayout 0 || qdbus org.kde.keyboard /Layouts setLayout 0", timeout=5)
                layout_switched = bool(res.get("ok"))
            except Exception:
                layout_switched = False
        cmd, tool, err = build_type_command(env=env, text=text, delay=delay, clear=clear)
        if err:
            return ctx.cors_json_response({"ok": False, "error": err}, status=500)
        result = await ctx.desktop_exec(cmd, timeout=15)
        if not result.get("ok"):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"Type failed ({tool}): {result.get('stderr', result.get('error', ''))}"}, status=500)
        return ctx.cors_json_response({"ok": True, "text": text, "tool": tool, "ensure_latin": ensure_latin, "layout_switched": layout_switched})

    async def handle_v1_desktop_key(request: web.Request) -> web.Response:
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
        guard = await _check_required_title(body)
        if guard:
            return guard
        ctx.control_record_agent_action()
        key = body.get("key")
        keys = body.get("keys")
        if not key and not keys:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'key' or 'keys' parameter"}, status=400)
        cmd, tool, err, key_label = build_key_command(env=ctx.detect_desktop_env(), key=key, keys=keys)
        if err:
            return ctx.cors_json_response({"ok": False, "error": err}, status=500)
        result = await ctx.desktop_exec(cmd, timeout=10)
        if not result.get("ok"):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"Key press failed ({tool}): {result.get('stderr', result.get('error', ''))}"}, status=500)
        return ctx.cors_json_response({"ok": True, "key": key_label, "tool": tool})

    async def handle_v1_desktop_mouse(request: web.Request) -> web.Response:
        r = ctx.require_auth(request)
        if r:
            return r
        ctrl_err = ctx.control_check()
        if ctrl_err:
            return ctx.cors_json_response(ctrl_err, status=403)
        ctx.record_request()
        ctx.control_record_agent_action()
        try:
            body = await request.json()
        except Exception:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "Invalid JSON body"}, status=400)
        x = body.get("x")
        y = body.get("y")
        if x is None or y is None:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": "missing 'x' and/or 'y'"}, status=400)
        cmd, tool, err = build_mouse_command(env=ctx.detect_desktop_env(), x=int(x), y=int(y), absolute=body.get("absolute", True))
        if err:
            return ctx.cors_json_response({"ok": False, "error": err}, status=500)
        result = await ctx.desktop_exec(cmd, timeout=10)
        return ctx.cors_json_response({"ok": result.get("ok"), "x": int(x), "y": int(y), "absolute": body.get("absolute", True), "tool": tool})

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

    return DesktopHandlers(
        screenshot=handle_v1_desktop_screenshot,
        click=handle_v1_desktop_click,
        type=handle_v1_desktop_type,
        key=handle_v1_desktop_key,
        mouse=handle_v1_desktop_mouse,
        windows=handle_v1_desktop_windows,
        active_window=handle_v1_desktop_active_window,
        focus=handle_v1_desktop_focus,
    )
