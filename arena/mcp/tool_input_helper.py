"""MCP tools for the Interactive Input Helper (v4.152.0)."""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.tool_utils import text_content


def handle_input_helper_tool(name: str, args: dict[str, Any], *, ctx=None) -> dict[str, Any] | None:
    from arena.input_helper import client as _ih

    if name == "input_helper.health":
        return text_content(json.dumps(_ih.health(), ensure_ascii=False))

    if name == "input_helper.click":
        x = args.get("x")
        y = args.get("y")
        if x is None or y is None:
            return text_content(json.dumps({"ok": False, "error": "x and y required"}, ensure_ascii=False))
        try:
            result = _ih.click(int(x), int(y), button=str(args.get("button", "left")), double=bool(args.get("double", False)))
            return text_content(json.dumps(result, ensure_ascii=False))
        except Exception as e:
            return text_content(json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}", "hint": "Is the Input Helper running? Start it with: python arena/input_helper/helper_server.py"}, ensure_ascii=False))

    if name == "input_helper.move":
        try:
            result = _ih.move(int(args["x"]), int(args["y"]))
            return text_content(json.dumps(result, ensure_ascii=False))
        except Exception as e:
            return text_content(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))

    if name == "input_helper.type":
        try:
            result = _ih.type_text(str(args.get("text", "")), delay_ms=int(args.get("delay_ms", 5)))
            return text_content(json.dumps(result, ensure_ascii=False))
        except Exception as e:
            return text_content(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))

    if name == "input_helper.key":
        try:
            result = _ih.key(str(args.get("name", "")), modifiers=args.get("modifiers"))
            return text_content(json.dumps(result, ensure_ascii=False))
        except Exception as e:
            return text_content(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))

    if name == "input_helper.launch":
        try:
            result = _ih.launch(str(args.get("path", "")), args=args.get("args"))
            return text_content(json.dumps(result, ensure_ascii=False))
        except Exception as e:
            return text_content(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))

    if name == "input_helper.send_chat_command":
        try:
            result = _ih.send_chat_command(
                command=str(args.get("command", "")),
                hwnd=args.get("hwnd"),
                open_key=str(args.get("open_key", "/")),
            )
            return text_content(json.dumps(result, ensure_ascii=False))
        except Exception as e:
            return text_content(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))

    return None


INPUT_HELPER_TOOLS = [
    {"name": "input_helper.health", "description": "Check if the Interactive Input Helper is running in the user's desktop session.", "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "input_helper.click", "description": "Send a real hardware mouse click via the Interactive Input Helper (works for Java Swing, LWJGL, any GUI). Requires the helper to be running in the user's session.", "inputSchema": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}, "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"}, "double": {"type": "boolean", "default": False}}, "required": ["x", "y"], "additionalProperties": False}},
    {"name": "input_helper.move", "description": "Move the mouse cursor to absolute screen coordinates via the Interactive Input Helper.", "inputSchema": {"type": "object", "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}}, "required": ["x", "y"], "additionalProperties": False}},
    {"name": "input_helper.type", "description": "Type unicode text into the focused window via the Interactive Input Helper (SendInput UNICODE).", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}, "delay_ms": {"type": "integer", "default": 5}}, "required": ["text"], "additionalProperties": False}},
    {"name": "input_helper.key", "description": "Press a named key with optional modifiers via the Interactive Input Helper (e.g. 'enter', 'escape', 'f3', 'a' with ['ctrl']).", "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "modifiers": {"type": "array", "items": {"type": "string"}}}, "required": ["name"], "additionalProperties": False}},
    {"name": "input_helper.launch", "description": "Launch an application in the user's interactive desktop session (solves Session 0 GUI launch limitation).", "inputSchema": {"type": "object", "properties": {"path": {"type": "string"}, "args": {"type": "array", "items": {"type": "string"}}}, "required": ["path"], "additionalProperties": False}},
    {"name": "input_helper.send_chat_command", "description": "Send a command to a Minecraft/LWJGL game via the chat: focus window, press /, type command, press Enter. All via real SendInput.", "inputSchema": {"type": "object", "properties": {"command": {"type": "string"}, "hwnd": {"type": "integer"}, "open_key": {"type": "string", "default": "/"}}, "required": ["command"], "additionalProperties": False}},
]


__all__ = ["INPUT_HELPER_TOOLS", "handle_input_helper_tool"]
