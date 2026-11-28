"""MCP `desktop.wait`: wait on the host for a window, a screen change or text (#621)."""
from __future__ import annotations

import json
from typing import Any

from arena.desktop.wait_schema import wait_request_schema
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


DESKTOP_WAIT_MCP_TOOLS = [
    {
        "name": "desktop.wait",
        "description": (
            "Wait on the host until something is true of the desktop, instead of sleeping and taking "
            "screenshots. for=window: a window whose title or class contains the given words is present, "
            "absent, or active (in front). for=screen: the picture changes (compared with the first look, so "
            "call this before the change you expect can have finished), or stops changing for stable_ms. "
            "for=text: the words are on the screen, or no longer are (needs tesseract; English only). "
            "screen and text look at screen captures, and on Windows a game in exclusive full screen is "
            "captured as a picture that never changes, so they cannot watch one. "
            "Returns happened: true or false with waited_ms and what was seen; running out of time is not an "
            "error. At most 45 s per call: for longer waits call again."
        ),
        "inputSchema": wait_request_schema(),
    },
]

__all__ = ["DESKTOP_WAIT_MCP_TOOLS", "handle_desktop_wait_tool"]
