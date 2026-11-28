"""The request a desktop wait takes, written once for the HTTP document and for the MCP tool (#621)."""
from __future__ import annotations

from typing import Any

from arena.desktop.wait import (
    DEFAULT_POLL_MS,
    DEFAULT_STABLE_MS,
    DEFAULT_TIMEOUT_MS,
    FIELDS,
    MAX_POLL_MS,
    MAX_TIMEOUT_MS,
    MIN_POLL_MS,
    REGION_BOUNDS,
)

# Two copies of this were two chances to describe a field the planner does
# not take, or a limit it does not have. `plan_wait` is what decides; this
# says what it decides, and the tests ask both.


def _region() -> dict[str, Any]:
    return {
        "type": "object",
        "description": (
            "screen, text: look at this rectangle only, in desktop pixels. Default: the whole desktop. A host that "
            "cannot cut its capture to a region (no Pillow, where the capture tool takes the whole desktop) is "
            "refused and does not watch the whole desktop instead."),
        "properties": {name: {"type": "integer", "minimum": least, "maximum": most}
                       for name, (least, most) in REGION_BOUNDS.items()},
        "required": list(REGION_BOUNDS),
        "additionalProperties": False,
    }


def wait_request_schema() -> dict[str, Any]:
    """A fresh JSON Schema of the request body on every call: callers edit what they are given."""
    return {
        "type": "object",
        "properties": {
            "for": {"type": "string", "enum": list(FIELDS), "description": "What to wait for."},
            "timeout_ms": {"type": "integer", "minimum": 1, "maximum": MAX_TIMEOUT_MS, "default": DEFAULT_TIMEOUT_MS,
                           "description": "Give up after this long. For a longer wait, call again."},
            "poll_ms": {"type": "integer", "minimum": MIN_POLL_MS, "maximum": MAX_POLL_MS,
                        "default": DEFAULT_POLL_MS, "description": "Pause between looks."},
            "title": {"type": "string", "description": "window: words from the window title."},
            "class": {"type": "string", "description": (
                "window: words from the window class. Refused with a 500 where the host's window list "
                "has no classes (wmctrl, xdotool).")},
            "state": {"type": "string", "enum": ["present", "absent", "active"], "default": "present",
                      "description": "window: present, absent or active (in front). text: present or absent."},
            "until": {"type": "string", "enum": ["change", "stable"], "default": "change",
                      "description": "screen: a change since the first look, or no change for `stable_ms`."},
            "stable_ms": {"type": "integer", "minimum": MIN_POLL_MS, "maximum": MAX_TIMEOUT_MS,
                          "default": DEFAULT_STABLE_MS,
                          "description": "screen, until=stable only: how long the picture must stay the same."},
            "text": {"type": "string", "description": "text: the words to look for (OCR)."},
            "min_confidence": {"type": "integer", "minimum": 0, "maximum": 100, "default": 40,
                               "description": "text: ignore words read with less confidence."},
            "region": _region(),
        },
        "required": ["for"],
        "additionalProperties": False,
    }


__all__ = ["wait_request_schema"]
