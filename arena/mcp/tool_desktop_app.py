"""Window-relative desktop app MCP helpers.

These tools compose the existing desktop endpoints into app/window-relative
operations.  They are intentionally thin: the bridge still performs the real
window enumeration, focus, screenshot, and input work; this layer makes GUI
scenarios less coordinate-fragile by resolving a target window first and only
then converting relative coordinates to absolute desktop coordinates.
"""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_desktop import _bridge_call, _bridge_get
from arena.mcp.tool_utils import text_content


def _filters(args: dict[str, Any]) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for src, dst in (
        ("id", "id"),
        ("title", "title"),
        ("class", "class"),
        ("desktop_file", "desktop_file"),
        ("resource_name", "resource_name"),
        ("pid", "pid"),
        ("display", "display"),
        ("active_only", "active_only"),
    ):
        value = args.get(src)
        if value not in (None, ""):
            params[dst] = value
    if "include_displays" in args:
        params["include_displays"] = args.get("include_displays")
    return params


def _geom(window: dict[str, Any]) -> dict[str, int] | None:
    raw = window.get("geometry") or {}
    try:
        x = int(raw.get("x", 0))
        y = int(raw.get("y", 0))
        width = int(raw.get("width", 0))
        height = int(raw.get("height", 0))
    except (TypeError, ValueError, AttributeError):
        return None
    if width <= 0 or height <= 0:
        return None
    return {"x": x, "y": y, "width": width, "height": height}


def _resolve(ctx, args: dict[str, Any]) -> dict[str, Any]:
    params = _filters(args)
    params.setdefault("include_displays", bool(args.get("include_displays", False)))
    listing = _bridge_get(ctx, "/v1/desktop/windows", params)
    windows = list(listing.get("windows") or [])
    window_id = str(args.get("id", "") or "").strip()
    target = None
    if window_id:
        for window in windows:
            if str(window.get("id")) == window_id or str(window.get("internal_id")) == window_id:
                target = window
                break
    if target is None and windows:
        target = windows[0]
    max_candidates = int(args.get("max_candidates", 5) or 5)
    return {"listing": listing, "target": target, "candidates": windows[: max(1, max_candidates)]}


def _target_or_error(ctx, args: dict[str, Any]) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    resolved = _resolve(ctx, args)
    target = resolved.get("target")
    if not target:
        return None, {"ok": False, "error": "window_not_found", "candidates": resolved.get("candidates", []), "filters": _filters(args)}
    geom = _geom(target)
    if not geom:
        return None, {"ok": False, "error": "window_geometry_unavailable", "target": target, "candidates": resolved.get("candidates", [])}
    return target, {"resolved": resolved, "geometry": geom}


def _find(ctx, args: dict[str, Any]) -> dict[str, Any]:
    resolved = _resolve(ctx, args)
    target = resolved.get("target")
    payload = {
        "ok": bool(target),
        "target": target,
        "geometry": _geom(target or {}),
        "candidates": resolved.get("candidates", []),
        "all_count": resolved.get("listing", {}).get("all_count", resolved.get("listing", {}).get("count")),
        "filters": _filters(args),
    }
    if not target:
        payload["error"] = "window_not_found"
    return payload


def _focus(ctx, args: dict[str, Any]) -> dict[str, Any]:
    target, meta = _target_or_error(ctx, args)
    if not target:
        return meta
    focus_args = _filters(args)
    focus_args["id"] = target.get("id") or target.get("internal_id")
    focus_args["verify"] = args.get("verify", True)
    focus_args["timeout_ms"] = args.get("timeout_ms", 1500)
    result = _bridge_call(ctx, "/v1/desktop/focus", focus_args)
    result["target"] = target
    result["geometry"] = meta["geometry"]
    return result


def _refocus_and_reresolve(ctx, args: dict[str, Any], target: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Focus target, then re-read its geometry.

    Windows reports minimized windows at parking coordinates like
    (-32000, -32000), and some apps expose a tiny owner window before
    restore.  Window-relative clicks must be computed from the post-focus
    geometry, not from the stale pre-focus listing.
    """
    focus_args = {"id": target.get("id") or target.get("internal_id"), "verify": args.get("verify_focus", True), "timeout_ms": args.get("timeout_ms", 1500)}
    focus_res = _bridge_call(ctx, "/v1/desktop/focus", focus_args)
    refreshed = None
    if focus_res.get("ok"):
        refreshed_resolved = _resolve(ctx, {**args, "id": target.get("id") or target.get("internal_id")})
        refreshed = refreshed_resolved.get("target") or target
    return focus_res, refreshed


def _click_window_relative(ctx, args: dict[str, Any]) -> dict[str, Any]:
    resolved = _resolve(ctx, args)
    target = resolved.get("target")
    if not target:
        return {"ok": False, "error": "window_not_found", "candidates": resolved.get("candidates", []), "filters": _filters(args)}
    if args.get("x") is None or args.get("y") is None:
        return {"ok": False, "error": "missing 'x' and/or 'y' relative coordinates"}
    focus_res = None
    if args.get("focus", True):
        focus_res, refreshed = _refocus_and_reresolve(ctx, args, target)
        if not focus_res.get("ok") and args.get("require_focus", True):
            focus_res["target"] = target
            focus_res["geometry"] = _geom(target)
            return focus_res
        if refreshed:
            target = refreshed
    geom = _geom(target)
    if not geom:
        return {"ok": False, "error": "window_geometry_unavailable_after_focus" if focus_res else "window_geometry_unavailable", "target": target, "candidates": resolved.get("candidates", []), "focus": focus_res}
    rel_x = int(args["x"])
    rel_y = int(args["y"])
    allow_outside = bool(args.get("allow_outside", False))
    if not allow_outside and not (0 <= rel_x < geom["width"] and 0 <= rel_y < geom["height"]):
        return {"ok": False, "error": "relative_point_outside_window", "x": rel_x, "y": rel_y, "geometry": geom, "target": target}
    abs_x = geom["x"] + rel_x
    abs_y = geom["y"] + rel_y
    click_args: dict[str, Any] = {
        "x": abs_x,
        "y": abs_y,
        "button": args.get("button", "left"),
        "double": args.get("double", False),
        "activate": args.get("activate", True),
    }
    guard = args.get("require_active_title")
    if guard:
        click_args["require_active_title"] = guard
    result = _bridge_call(ctx, "/v1/desktop/click", click_args)
    result.update({
        "target": target,
        "geometry": geom,
        "relative": {"x": rel_x, "y": rel_y},
        "absolute": {"x": abs_x, "y": abs_y},
    })
    if focus_res is not None:
        result["focus"] = focus_res
    return result


def _screenshot_window(ctx, args: dict[str, Any]) -> dict[str, Any]:
    resolved = _resolve(ctx, args)
    target = resolved.get("target")
    if not target:
        return {"ok": False, "error": "window_not_found", "candidates": resolved.get("candidates", []), "filters": _filters(args)}
    focus_res = None
    if args.get("focus", True):
        focus_res, refreshed = _refocus_and_reresolve(ctx, args, target)
        if not focus_res.get("ok") and args.get("require_focus", True):
            focus_res["target"] = target
            return focus_res
        if refreshed:
            target = refreshed
    geom = _geom(target)
    if not geom:
        return {"ok": False, "error": "window_geometry_unavailable_after_focus" if focus_res else "window_geometry_unavailable", "target": target, "candidates": resolved.get("candidates", []), "focus": focus_res}
    if str(args.get("format", "base64") or "base64").lower() != "base64":
        return {"ok": False, "error": "desktop_app.screenshot_window returns JSON, so only format='base64' is supported; use /v1/desktop/screenshot directly for binary formats", "target": target, "geometry": geom}
    params: dict[str, Any] = {
        "format": "base64",
        "region_x": geom["x"],
        "region_y": geom["y"],
        "region_width": geom["width"],
        "region_height": geom["height"],
        "quality": args.get("quality", 80),
    }
    if args.get("scale") is not None:
        params["scale"] = args.get("scale")
    if args.get("max_width") is not None:
        params["max_width"] = args.get("max_width")
    shot = _bridge_get(ctx, "/v1/desktop/screenshot", params)
    shot.update({"target": target, "geometry": geom})
    if focus_res is not None:
        shot["focus"] = focus_res
    return shot


def _type_window(ctx, args: dict[str, Any]) -> dict[str, Any]:
    target, meta = _target_or_error(ctx, args)
    if not target:
        return meta
    focus_res = _bridge_call(ctx, "/v1/desktop/focus", {"id": target.get("id") or target.get("internal_id"), "verify": args.get("verify_focus", True), "timeout_ms": args.get("timeout_ms", 1500)})
    if not focus_res.get("ok") and args.get("require_focus", True):
        focus_res["target"] = target
        return focus_res
    type_args = {
        "text": args.get("text", ""),
        "delay": args.get("delay", 50),
        "clear": args.get("clear", False),
        "ensure_latin": args.get("ensure_latin", True),
    }
    if args.get("require_active_title"):
        type_args["require_active_title"] = args.get("require_active_title")
    result = _bridge_call(ctx, "/v1/desktop/type", type_args)
    result.update({"target": target, "geometry": meta["geometry"], "focus": focus_res})
    return result


def _key_window(ctx, args: dict[str, Any]) -> dict[str, Any]:
    target, meta = _target_or_error(ctx, args)
    if not target:
        return meta
    focus_res = _bridge_call(ctx, "/v1/desktop/focus", {"id": target.get("id") or target.get("internal_id"), "verify": args.get("verify_focus", True), "timeout_ms": args.get("timeout_ms", 1500)})
    if not focus_res.get("ok") and args.get("require_focus", True):
        focus_res["target"] = target
        return focus_res
    key_args: dict[str, Any] = {}
    if args.get("key") is not None:
        key_args["key"] = args.get("key")
    if args.get("keys") is not None:
        key_args["keys"] = args.get("keys")
    if args.get("require_active_title"):
        key_args["require_active_title"] = args.get("require_active_title")
    result = _bridge_call(ctx, "/v1/desktop/key", key_args)
    result.update({"target": target, "geometry": meta["geometry"], "focus": focus_res})
    return result


def handle_desktop_app_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    handlers = {
        "desktop_app.find": _find,
        "desktop_app.focus": _focus,
        "desktop_app.click_window_relative": _click_window_relative,
        "desktop_app.screenshot_window": _screenshot_window,
        "desktop_app.type_window": _type_window,
        "desktop_app.key_window": _key_window,
    }
    fn = handlers.get(name)
    if not fn:
        return None
    return text_content(json.dumps(fn(ctx, args), ensure_ascii=False))


_DESKTOP_APP_FILTER_PROPS: dict[str, Any] = {
    "id": {"type": "string", "description": "Window id/internal_id. If provided, it wins over title/class ranking."},
    "title": {"type": "string", "description": "Case-insensitive substring of the window title."},
    "class": {"type": "string", "description": "Case-insensitive substring of the window class/resource_class."},
    "desktop_file": {"type": "string"},
    "resource_name": {"type": "string"},
    "pid": {"type": "integer"},
    "display": {"type": "string"},
    "active_only": {"type": "boolean", "default": False},
    "max_candidates": {"type": "integer", "default": 5},
}


DESKTOP_APP_MCP_TOOLS = [
    {
        "name": "desktop_app.find",
        "description": "Find and rank a real desktop app/window, returning the chosen target geometry for window-relative automation.",
        "inputSchema": {"type": "object", "properties": {**_DESKTOP_APP_FILTER_PROPS, "include_displays": {"type": "boolean", "default": False}}, "additionalProperties": False},
    },
    {
        "name": "desktop_app.focus",
        "description": "Resolve a desktop app/window by title/class/pid/id and focus it, returning the resolved target and geometry.",
        "inputSchema": {"type": "object", "properties": {**_DESKTOP_APP_FILTER_PROPS, "verify": {"type": "boolean", "default": True}, "timeout_ms": {"type": "integer", "default": 1500}}, "additionalProperties": False},
    },
    {
        "name": "desktop_app.click_window_relative",
        "description": "Resolve a window, convert relative x/y inside that window into absolute desktop coordinates, optionally focus it, then click. This avoids brittle whole-screen coordinates.",
        "inputSchema": {"type": "object", "properties": {**_DESKTOP_APP_FILTER_PROPS, "x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"}, "double": {"type": "boolean", "default": False}, "focus": {"type": "boolean", "default": True}, "require_focus": {"type": "boolean", "default": True}, "verify_focus": {"type": "boolean", "default": True}, "timeout_ms": {"type": "integer", "default": 1500}, "activate": {"type": "boolean", "default": True}, "allow_outside": {"type": "boolean", "default": False}, "require_active_title": {"type": "string"}}, "required": ["x", "y"], "additionalProperties": False},
    },
    {
        "name": "desktop_app.screenshot_window",
        "description": "Resolve a window and return a base64 screenshot cropped to that window geometry.",
        "inputSchema": {"type": "object", "properties": {**_DESKTOP_APP_FILTER_PROPS, "format": {"type": "string", "enum": ["base64"], "default": "base64"}, "scale": {"type": "number"}, "max_width": {"type": "integer"}, "quality": {"type": "integer", "default": 80}}, "additionalProperties": False},
    },
    {
        "name": "desktop_app.type_window",
        "description": "Resolve/focus a window and type text into it with the usual desktop.type guards.",
        "inputSchema": {"type": "object", "properties": {**_DESKTOP_APP_FILTER_PROPS, "text": {"type": "string"}, "delay": {"type": "integer", "default": 50}, "clear": {"type": "boolean", "default": False}, "ensure_latin": {"type": "boolean", "default": True}, "require_focus": {"type": "boolean", "default": True}, "verify_focus": {"type": "boolean", "default": True}, "timeout_ms": {"type": "integer", "default": 1500}, "require_active_title": {"type": "string"}}, "required": ["text"], "additionalProperties": False},
    },
    {
        "name": "desktop_app.key_window",
        "description": "Resolve/focus a window and press a key or key chord inside it.",
        "inputSchema": {"type": "object", "properties": {**_DESKTOP_APP_FILTER_PROPS, "key": {"type": "string"}, "keys": {"type": "array", "items": {"type": "string"}}, "require_focus": {"type": "boolean", "default": True}, "verify_focus": {"type": "boolean", "default": True}, "timeout_ms": {"type": "integer", "default": 1500}, "require_active_title": {"type": "string"}}, "additionalProperties": False},
    },
]


__all__ = ["DESKTOP_APP_MCP_TOOLS", "handle_desktop_app_tool"]
