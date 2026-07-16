"""Desktop input endpoint handlers."""
from __future__ import annotations

import shutil

from aiohttp import web

from arena.desktop.input import build_click_command, build_key_command, build_mouse_command, build_type_command
from arena.handler_context import DesktopHandlerContext
from arena.handler_helpers import controlled, err_json


def make_desktop_input_handlers(ctx: DesktopHandlerContext):
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

    @controlled(ctx)
    async def handle_v1_desktop_click(request: web.Request) -> web.Response:
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

    @controlled(ctx)
    async def handle_v1_desktop_type(request: web.Request) -> web.Response:
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

    @controlled(ctx)
    async def handle_v1_desktop_key(request: web.Request) -> web.Response:
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

    @controlled(ctx)
    async def handle_v1_desktop_mouse(request: web.Request) -> web.Response:
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

    return handle_v1_desktop_click, handle_v1_desktop_type, handle_v1_desktop_key, handle_v1_desktop_mouse
