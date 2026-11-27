"""MCP `desktop.sequence`: held keys, relative motion and timing in one call (#616)."""
from __future__ import annotations

import json
import urllib.error
from typing import Any

from arena.jsonshape import loads_object
from arena.mcp.image_result import error_result
from arena.mcp.tool_desktop import _bridge_call
from arena.mcp.tool_utils import text_content

#: Added to the sequence's own duration: the route answers only when it is done.
_TIMEOUT_MARGIN_S = 15
_MAX_TIMEOUT_S = 90


def _timeout(args: dict[str, Any]) -> float:
    """Long enough for the steps to finish; the route itself refuses anything over a minute."""
    steps = args.get("steps") if isinstance(args.get("steps"), list) else []
    total_ms = sum(step.get("ms", 0) for step in steps
                   if isinstance(step, dict) and isinstance(step.get("ms"), int))
    return min(_MAX_TIMEOUT_S, total_ms / 1000 + _TIMEOUT_MARGIN_S)


def _refusal(exc: urllib.error.HTTPError) -> dict[str, Any]:
    """Keep the bridge's own explanation when the route refuses or stops early."""
    body = exc.read().decode("utf-8", "replace")
    try:
        answer = loads_object(body)
    except ValueError:
        answer = {}
    return answer or {"ok": False, "error": f"sequence failed with HTTP {exc.code}", "detail": body[:500]}


def handle_desktop_sequence_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    """Dispatch ``desktop.sequence``; a refusal comes back in the bridge's own words."""
    if name != "desktop.sequence":
        return None
    try:
        result = _bridge_call(ctx, "/v1/desktop/sequence", args, timeout=_timeout(args))
    except urllib.error.HTTPError as exc:
        return error_result(_refusal(exc))
    return text_content(json.dumps(result, ensure_ascii=False))


_KEY = {"type": "string", "description": "Key name: a letter, a digit, space, shift, ctrl, alt, esc, enter, "
                                         "tab, f1..f12, an arrow (left, up, right, down), and similar."}
_BUTTON = {"type": "string", "enum": ["left", "right", "middle"], "default": "left"}

DESKTOP_SEQUENCE_MCP_TOOLS = [
    {
        "name": "desktop.sequence",
        "description": (
            "Run a list of timed input steps on the host in one call: hold a key or a mouse button, move the "
            "pointer by a delta, scroll the wheel, wait. Use it where desktop.key and desktop.click are not "
            "enough: holding, relative motion, or two actions timed against each other. Everything still "
            "held is released when the sequence ends. `require_active_title` is mandatory; the sequence "
            "stops as soon as another window is in front. One key or button may stay down for 15 s and the "
            "whole sequence may run for 60 s. Native Windows input only for now."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 200,
                    "items": {
                        "type": "object",
                        "properties": {
                            "do": {"type": "string", "enum": [
                                "wait", "key_down", "key_up", "tap", "mouse_down", "mouse_up", "click",
                                "move", "move_to", "scroll"]},
                            "key": _KEY,
                            "button": _BUTTON,
                            "ms": {"type": "integer", "description": "wait: how long. tap, click: how long "
                                   "the press lasts (default 60). move: spread the motion over this time."},
                            "dx": {"type": "integer", "description": "move: horizontal delta in mouse counts."},
                            "dy": {"type": "integer", "description": "move: vertical delta in mouse counts."},
                            "x": {"type": "integer", "description": "move_to: desktop x in physical pixels."},
                            "y": {"type": "integer", "description": "move_to: desktop y in physical pixels."},
                            "clicks": {"type": "integer", "description": "scroll: wheel notches, positive is up."},
                        },
                        "required": ["do"],
                        "additionalProperties": False,
                    },
                },
                "require_active_title": {
                    "type": "string",
                    "description": "The foreground window title must contain this, before and during the sequence.",
                },
            },
            "required": ["steps", "require_active_title"],
            "additionalProperties": False,
        },
    },
]

__all__ = ["DESKTOP_SEQUENCE_MCP_TOOLS", "handle_desktop_sequence_tool"]
