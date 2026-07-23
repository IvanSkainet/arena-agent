"""Extends arena/mcp/tool_desktop.py with click/type/key/mouse.

These four handlers wrap the existing /v1/desktop/click, /v1/desktop/type,
/v1/desktop/key, /v1/desktop/mouse HTTP endpoints. Same rationale as
v4.56.0 mobile.* — the HTTP is production-tested since v3.8x, we just
expose it as typed MCP tools so scenarios and the chat extension can
call it directly.
"""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_desktop import _bridge_call
from arena.mcp.tool_utils import text_content


def handle_desktop_input_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    if name == "desktop.click":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/click", args), ensure_ascii=False))
    if name == "desktop.type":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/type", args), ensure_ascii=False))
    if name == "desktop.key":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/key", args), ensure_ascii=False))
    if name == "desktop.mouse":
        return text_content(json.dumps(_bridge_call(ctx, "/v1/desktop/mouse", args), ensure_ascii=False))
    return None


DESKTOP_INPUT_MCP_TOOLS = [
    {
        "name": "desktop.click",
        "description": (
            "Click at absolute screen coordinates. Works on Wayland "
            "(via wtype/ydotool) and X11 (xdotool). Optional `button` "
            "(left|right|middle), `double`, `activate` (bring window "
            "under cursor to front first), `require_active_title` guard."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                "double": {"type": "boolean", "default": False},
                "activate": {"type": "boolean", "default": True},
                "require_active_title": {"type": "string", "description": "Refuse to click unless active window title contains this substring."},
            },
            "required": ["x", "y"], "additionalProperties": False},
    },
    {
        "name": "desktop.type",
        "description": (
            "Type text into the focused window. `ensure_latin` (default true) "
            "switches KDE keyboard layout to 0 first so shortcuts and English "
            "URLs work regardless of current layout. `clear` selects all + "
            "deletes before typing. `delay` ms between keys."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "delay": {"type": "integer", "default": 50},
                "clear": {"type": "boolean", "default": False},
                "ensure_latin": {"type": "boolean", "default": True},
                "require_active_title": {"type": "string"},
            },
            "required": ["text"], "additionalProperties": False},
    },
    {
        "name": "desktop.key",
        "description": (
            "Press a single key or key combo. `key='Return'` for one key, "
            "`keys=['ctrl','l']` for a chord (Ctrl+L). Names follow "
            "xdotool/wtype conventions."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Single key name (Return, Escape, Tab, F5, ...)"},
                "keys": {"type": "array", "items": {"type": "string"}, "description": "Key chord to press together"},
                "require_active_title": {"type": "string"},
            }, "additionalProperties": False},
    },
    {
        "name": "desktop.mouse",
        "description": "Move mouse cursor to (x, y). `absolute` true (default) uses screen coords, false uses relative delta.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "absolute": {"type": "boolean", "default": True},
            },
            "required": ["x", "y"], "additionalProperties": False},
    },
]

__all__ = ["handle_desktop_input_tool", "DESKTOP_INPUT_MCP_TOOLS"]
