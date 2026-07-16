"""Desktop OCR endpoint handlers."""
from __future__ import annotations

import shutil

from aiohttp import web

from arena.desktop.displays import get_displays, match_display
from arena.desktop.input import build_click_command
from arena.handler_context import DesktopHandlerContext
from arena.handler_helpers import controlled, authed, err_json


class DesktopOcrHandlers(tuple):
    __slots__ = ()
    _fields = ("ocr", "find_text", "click_text")

    def __new__(cls, ocr, find_text, click_text):
        return super().__new__(cls, (ocr, find_text, click_text))

    ocr = property(lambda self: self[0])
    find_text = property(lambda self: self[1])
    click_text = property(lambda self: self[2])



def _target_point(match: dict, position: str, offset_x: int, offset_y: int) -> tuple[int, int]:
    bbox = match.get("bbox") or {}
    left = int(bbox.get("x", 0))
    top = int(bbox.get("y", 0))
    width = int(bbox.get("width", 0))
    height = int(bbox.get("height", 0))
    center = match.get("center") or {"x": left + width // 2, "y": top + height // 2}
    x = int(center.get("x", left + width // 2))
    y = int(center.get("y", top + height // 2))
    position = str(position or "center").lower()
    if position == "left":
        x = left
    elif position == "right":
        x = left + width
    elif position == "top":
        y = top
    elif position == "bottom":
        y = top + height
    return x + int(offset_x or 0), y + int(offset_y or 0)



def make_desktop_ocr_handlers(ctx: DesktopHandlerContext) -> DesktopOcrHandlers:
    async def _run_ocr(data: dict, *, query_required: bool) -> tuple[dict | None, web.Response | None]:
        query = str(data.get("query", "") or "").strip()
        if query_required and not query:
            ctx.record_request(is_error=True, count_request=False)
            return None, ctx.cors_json_response({"ok": False, "error": "missing query"}, status=400)
        prefer_active_window = bool(data.get("prefer_active_window", False))
        within_active_window = bool(data.get("within_active_window", False))
        require_active_title = str(data.get("require_active_title", "") or "").strip()
        active_window = None
        if prefer_active_window or within_active_window or require_active_title:
            active_window = await ctx.get_active_window()
            if require_active_title and (
                not active_window or require_active_title.lower() not in str(active_window.get("title", "")).lower()
            ):
                ctx.record_request(is_error=True, count_request=False)
                return None, ctx.cors_json_response(
                    {
                        "ok": False,
                        "error": "input_guard_failed",
                        "message": "Active window does not match required title",
                        "active_window": active_window,
                        "required_title_contains": require_active_title,
                    },
                    status=409,
                )
        display_info = None
        display_name = str(data.get("display", "") or "").strip()
        if display_name:
            displays = await get_displays(desktop_exec=ctx.desktop_exec)
            display_info = match_display(displays.get("displays", []), display_name)
            if not display_info:
                ctx.record_request(is_error=True, count_request=False)
                return None, ctx.cors_json_response({"ok": False, "error": f"unknown display: {display_name}", "available_displays": displays.get("displays", [])}, status=404)
        result = await ctx.ocr_desktop(
            query=query,
            scale=data.get("scale"),
            max_width=data.get("max_width"),
            quality=int(data.get("quality", 80) or 80),
            min_confidence=int(data.get("min_confidence", 40) or 40),
            psm=int(data.get("psm", 11) or 11),
            max_results=int(data.get("max_results", 20) or 20),
            prefer_active_window=prefer_active_window,
            within_active_window=within_active_window,
            active_window=active_window,
            region_x=(display_info or {}).get("geometry", {}).get("x"),
            region_y=(display_info or {}).get("geometry", {}).get("y"),
            region_width=(display_info or {}).get("geometry", {}).get("width"),
            region_height=(display_info or {}).get("geometry", {}).get("height"),
            capture_screenshot=ctx.capture_screenshot,
            desktop_exec=ctx.desktop_exec,
            detect_env=ctx.detect_desktop_env,
            audit_fn=ctx.audit,
        )
        if not result.get("ok"):
            ctx.record_request(is_error=True, count_request=False)
            return None, ctx.cors_json_response(result, status=500)
        if display_info:
            result["display"] = display_info
        return result, None

    @authed(ctx)
    async def handle_v1_desktop_ocr(request: web.Request) -> web.Response:
        try:
            data = await request.json() if request.can_read_body else {}
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        result, error = await _run_ocr(data, query_required=False)
        return error or ctx.cors_json_response(result)

    @authed(ctx)
    async def handle_v1_desktop_find_text(request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        result, error = await _run_ocr(data, query_required=True)
        if error:
            return error
        if not result.get("matches"):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({**result, "error": f"no matches for query: {result['query']}"}, status=404)
        return ctx.cors_json_response(result)

    @controlled(ctx)
    async def handle_v1_desktop_click_text(request: web.Request) -> web.Response:
        try:
            data = await request.json()
        except Exception as e:
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({"ok": False, "error": f"invalid json: {e}"}, status=400)
        data = {"prefer_active_window": True, **data}
        result, error = await _run_ocr(data, query_required=True)
        if error:
            return error
        if not result.get("matches"):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response({**result, "error": f"no matches for query: {result['query']}"}, status=404)
        match = result["best_match"]
        x, y = _target_point(match, str(data.get("target_position", "center") or "center"), data.get("offset_x", 0), data.get("offset_y", 0))
        response = {
            **result,
            "target": {
                "x": x,
                "y": y,
                "position": str(data.get("target_position", "center") or "center"),
                "offset_x": int(data.get("offset_x", 0) or 0),
                "offset_y": int(data.get("offset_y", 0) or 0),
            },
        }
        if data.get("dry_run", False):
            return ctx.cors_json_response({**response, "clicked": False, "dry_run": True})
        env = ctx.detect_desktop_env()
        cmd, click_tool, err = build_click_command(
            env=env,
            x=x,
            y=y,
            button=str(data.get("button", "left") or "left"),
            double=bool(data.get("double", False)),
            activate=bool(data.get("activate", True)),
            has_kdotool=shutil.which("kdotool") is not None,
        )
        if err:
            return ctx.cors_json_response({"ok": False, "error": err}, status=500)
        exec_result = await ctx.desktop_exec(cmd, timeout=10)
        if not exec_result.get("ok"):
            ctx.record_request(is_error=True, count_request=False)
            return ctx.cors_json_response(
                {"ok": False, "error": f"Click failed ({click_tool}): {exec_result.get('stderr', exec_result.get('error', ''))}"},
                status=500,
            )
        ctx.control_record_agent_action()
        return ctx.cors_json_response({**response, "clicked": True, "dry_run": False, "click_tool": click_tool})

    return DesktopOcrHandlers(ocr=handle_v1_desktop_ocr, find_text=handle_v1_desktop_find_text, click_text=handle_v1_desktop_click_text)
