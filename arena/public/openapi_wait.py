"""The OpenAPI entry for POST /v1/desktop/wait (#621)."""
# Kept apart from `openapi.py`, like the sequence entry: that module's builder
# is one long literal.
from __future__ import annotations

from arena.desktop.wait import (
    DEFAULT_POLL_MS,
    DEFAULT_STABLE_MS,
    DEFAULT_TIMEOUT_MS,
    FIELDS,
    MAX_POLL_MS,
    MAX_TIMEOUT_MS,
    MIN_POLL_MS,
)
from arena.public.error_envelopes import _ERROR_ENVELOPE, _JSON_BODY_ERROR_ENVELOPE

_REGION = {
    "type": "object",
    "description": (
        "screen, text: look at this rectangle only, in desktop pixels. Default: the whole desktop. A host that "
        "cannot cut its capture to a region (no Pillow, where the capture tool takes the whole desktop) answers "
        "503 and does not watch the whole desktop instead."),
    "properties": {name: {"type": "integer"} for name in ("x", "y", "width", "height")},
    "required": ["x", "y", "width", "height"],
}
_ANSWER = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "happened": {"type": "boolean", "description": "false: the time ran out first. That is an answer, not an error."},
        "for": {"type": "string", "enum": list(FIELDS)},
        "waited_ms": {"type": "integer"},
        "polls": {"type": "integer", "description": "How many times the desktop was looked at."},
        "matches": {"type": "integer", "description": "window, text: how many matched at the last look."},
        "window": {"type": "object", "description": "window: the best match, or the active window that matched."},
        "active_window": {"type": "object", "nullable": True,
                          "description": "window, state=active, not matched: what was in front instead."},
        "compared": {"type": "string", "enum": ["pixels", "bytes"], "description": (
            "screen: how two captures were compared. `bytes` means the capture format could not be read as a "
            "picture, so a difference may be in the file and not on the screen.")},
        "still_ms": {"type": "integer", "description": "screen, until=stable: how long the picture has not changed."},
        "match": {"type": "object", "description": "text: the best match, with its box."},
        "word_count": {"type": "integer", "description": "text: words read at the last look."},
    },
    "required": ["ok", "happened", "for", "waited_ms", "polls"],
}


def _refusal(description: str, schema: dict | None = None) -> dict:
    return {"description": description, "content": {"application/json": {"schema": schema or _ERROR_ENVELOPE}}}


def wait_path_item() -> dict:
    """A fresh path item on every call: the builder's later passes edit operations in place."""
    return {"post": {
        "summary": "Wait on the host for a window, a screen change, or text on the screen",
        "description": (
            "One call instead of a sleep-and-screenshot loop. The bridge looks at the desktop every `poll_ms` "
            f"until the state is there or `timeout_ms` (at most {MAX_TIMEOUT_MS}) has passed, and looks once more "
            "at the deadline. Read-only: it sends no input and works while desktop control is paused. "
            "`for: screen` with `until: change` compares against the first look, so a change that finished "
            "before the call is not seen; `until: stable` has no such gap. A capture shows what the capture "
            "tool sees: on Windows an application in exclusive full screen is captured as a picture that does "
            "not change (#618), so `screen` and `text` waits cannot watch it. Fields that do not belong to the "
            "chosen `for` are refused."),
        "tags": ["Desktop"],
        "requestBody": {"content": {"application/json": {"schema": {
            "type": "object",
            "properties": {
                "for": {"type": "string", "enum": list(FIELDS)},
                "timeout_ms": {"type": "integer", "minimum": 1, "maximum": MAX_TIMEOUT_MS,
                               "default": DEFAULT_TIMEOUT_MS},
                "poll_ms": {"type": "integer", "minimum": MIN_POLL_MS, "maximum": MAX_POLL_MS,
                            "default": DEFAULT_POLL_MS},
                "title": {"type": "string", "description": "window: words from the window title."},
                "class": {"type": "string", "description": "window: words from the window class."},
                "state": {"type": "string", "enum": ["present", "absent", "active"], "default": "present",
                          "description": "window: present, absent or active (in front). text: present or absent."},
                "until": {"type": "string", "enum": ["change", "stable"], "default": "change",
                          "description": "screen: a change since the first look, or no change for `stable_ms`."},
                "stable_ms": {"type": "integer", "minimum": MIN_POLL_MS, "maximum": MAX_TIMEOUT_MS,
                              "default": DEFAULT_STABLE_MS, "description": "screen, until=stable only."},
                "text": {"type": "string", "description": "text: the words to look for (OCR)."},
                "min_confidence": {"type": "integer", "minimum": 0, "maximum": 100, "default": 40,
                                   "description": "text: ignore words read with less confidence."},
                "region": _REGION,
            },
            "required": ["for"],
        }}}},
        "responses": {
            "200": {"description": "The wait ended: `happened` says whether the state was reached",
                    "content": {"application/json": {"schema": _ANSWER}}},
            "400": _refusal("A field is missing, malformed, out of range or does not belong to this kind of "
                            "wait, or the body is not an object", _JSON_BODY_ERROR_ENVELOPE),
            "500": _refusal("The desktop could not be looked at: listing windows, capturing the screen or "
                            "reading it failed"),
        },
    }}
