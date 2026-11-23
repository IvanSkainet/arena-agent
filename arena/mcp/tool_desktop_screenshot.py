"""MCP ``desktop.screenshot``: one display or one region, returned as a picture."""
from __future__ import annotations

import urllib.error
from typing import Any

from arena.jsonshape import loads_object
from arena.mcp.image_result import error_result, shot_result
from arena.mcp.tool_desktop import _bridge_get

_DEFAULT_MAX_WIDTH = 1280
_REGION_KEYS = ("x", "y", "width", "height")


def _region_params(region: Any) -> dict[str, int] | None:
    if not isinstance(region, dict):
        return None
    try:
        values = {key: int(region[key]) for key in _REGION_KEYS}
    except (KeyError, TypeError, ValueError):
        return None
    if values["width"] <= 0 or values["height"] <= 0:
        return None
    return {f"region_{key}": value for key, value in values.items()}


def _display_names(listing: dict[str, Any], *, primary_only: bool = False) -> list[str]:
    displays = [d for d in listing.get("displays") or [] if isinstance(d, dict)]
    return [str(d["name"]) for d in displays if d.get("name") and (d.get("primary") or not primary_only)]


def _active_display(ctx) -> str:
    """Name the display to capture when the caller named none: active, else primary, else first by name."""
    listing = _bridge_get(ctx, "/v1/desktop/displays")
    names = _display_names(listing)
    candidates = [str(listing.get("active_output") or ""), *_display_names(listing, primary_only=True), *sorted(names)]
    return next((name for name in candidates if name in names), "")


def _target(ctx, args: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Return the capture parameters, or a refusal."""
    region = args.get("region")
    display = str(args.get("display") or "").strip()
    if region is not None and display:
        return {}, {"ok": False, "error": "use either 'display' or 'region', not both"}
    if region is not None:
        params = _region_params(region)
        if params is None:
            return {}, {"ok": False, "error": "region needs integer x, y, width > 0 and height > 0"}
        return params, None
    display = display or _active_display(ctx)
    return ({"display": display} if display else {}), None


def _screenshot(ctx, args: dict[str, Any]) -> dict[str, Any]:
    params, refusal = _target(ctx, args)
    if refusal:
        return error_result(refusal)
    params["format"] = "base64"
    if args.get("scale") is not None:
        params["scale"] = args.get("scale")
    else:
        params["max_width"] = args.get("max_width") or _DEFAULT_MAX_WIDTH
    return shot_result(_bridge_get(ctx, "/v1/desktop/screenshot", params))


def handle_desktop_screenshot_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    """Dispatch ``desktop.screenshot``; a bridge refusal comes back in its own words."""
    if name != "desktop.screenshot":
        return None
    try:
        return _screenshot(ctx, args)
    except urllib.error.HTTPError as exc:
        return error_result(_refusal(exc))


def _refusal(exc: urllib.error.HTTPError) -> dict[str, Any]:
    """Keep the bridge's own explanation when the screenshot route refuses."""
    body = exc.read().decode("utf-8", "replace")
    try:
        answer = loads_object(body)
    except ValueError:
        answer = {}
    return answer or {"ok": False, "error": f"screenshot failed with HTTP {exc.code}", "detail": body[:500]}


DESKTOP_SCREENSHOT_MCP_TOOLS = [
    {
        "name": "desktop.screenshot",
        "description": (
            "Capture one display or one desktop region and return it as an image, with the size of the picture "
            "and the scale that maps its pixels back to desktop coordinates. Without arguments it captures the "
            "active display, scaled down to 1280 pixels wide."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "display": {"type": "string", "description": "Display name from desktop.displays."},
                "region": {
                    "type": "object",
                    "description": "Desktop rectangle to capture instead of a display.",
                    "properties": {key: {"type": "integer"} for key in _REGION_KEYS},
                    "required": list(_REGION_KEYS),
                    "additionalProperties": False,
                },
                "max_width": {"type": "integer", "default": _DEFAULT_MAX_WIDTH,
                              "description": "Scale the picture down to this width."},
                "scale": {"type": "number", "description": "Explicit scale factor; replaces max_width."},
            },
            "additionalProperties": False,
        },
    },
]


__all__ = ["DESKTOP_SCREENSHOT_MCP_TOOLS", "handle_desktop_screenshot_tool"]
