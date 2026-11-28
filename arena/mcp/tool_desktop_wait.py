"""MCP `desktop.wait`: wait on the host for a window, a screen change or text (#621)."""
from __future__ import annotations

import json
from typing import Any

from arena.mcp.image_result import error_result

# The mission tools' helper, for the reasons `desktop.sequence` uses it: it
# waits 60 s for the bridge (a wait may take 45), and a refusal comes back as
# the body the bridge wrote.
from arena.mcp.tool_mission import _bridge_call
from arena.mcp.tool_utils import text_content


def handle_desktop_wait_tool(name: str, args: dict[str, Any], *, ctx) -> dict[str, Any] | None:
    """Dispatch ``desktop.wait``; "it did not happen in time" is an answer, a refusal is an error."""
    if name != "desktop.wait":
        return None
    result = _bridge_call(ctx, "/v1/desktop/wait", args)
    if result.get("ok") is False:
        return error_result(result)
    return text_content(json.dumps(result, ensure_ascii=False))


_REGION = {
    "type": "object",
    "description": "screen, text: look at this rectangle only (desktop pixels). Default: the whole desktop.",
    "properties": {name: {"type": "integer"} for name in ("x", "y", "width", "height")},
    "required": ["x", "y", "width", "height"],
    "additionalProperties": False,
}

DESKTOP_WAIT_MCP_TOOLS = [
    {
        "name": "desktop.wait",
        "description": (
            "Wait on the host until something is true of the desktop, instead of sleeping and taking "
            "screenshots. for=window: a window whose title or class contains the given words is present, "
            "absent, or active (in front). for=screen: the picture changes (compared with the first look, so "
            "call this before the change you expect can have finished), or stops changing for stable_ms. "
            "for=text: the words are on the screen, or no longer are (needs tesseract; English only). "
            "Returns happened: true or false with waited_ms and what was seen; running out of time is not an "
            "error. At most 45 s per call: for longer waits call again."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "for": {"type": "string", "enum": ["window", "screen", "text"]},
                "timeout_ms": {"type": "integer", "minimum": 1, "maximum": 45000, "default": 10000},
                "poll_ms": {"type": "integer", "minimum": 100, "maximum": 5000, "default": 500,
                            "description": "Pause between looks."},
                "title": {"type": "string", "description": "window: words from the window title."},
                "class": {"type": "string", "description": "window: words from the window class."},
                "state": {"type": "string", "enum": ["present", "absent", "active"], "default": "present",
                          "description": "window: present, absent or active. text: present or absent."},
                "until": {"type": "string", "enum": ["change", "stable"], "default": "change",
                          "description": "screen: wait for a change, or for the picture to stop changing."},
                "stable_ms": {"type": "integer", "minimum": 100, "maximum": 45000, "default": 1000,
                              "description": "screen, until=stable: how long the picture must stay the same."},
                "text": {"type": "string", "description": "text: the words to look for."},
                "min_confidence": {"type": "integer", "minimum": 0, "maximum": 100, "default": 40,
                                   "description": "text: ignore words read with less confidence."},
                "region": _REGION,
            },
            "required": ["for"],
            "additionalProperties": False,
        },
    },
]

__all__ = ["DESKTOP_WAIT_MCP_TOOLS", "handle_desktop_wait_tool"]
