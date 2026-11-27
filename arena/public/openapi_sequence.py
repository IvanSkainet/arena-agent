"""The OpenAPI entry for POST /v1/desktop/sequence (#616)."""
# Kept apart from `openapi.py`: that module's builder is one long literal, and
# this operation has more refusals worth documenting than fit on a line of it.
from __future__ import annotations

from arena.public.error_envelopes import _ERROR_ENVELOPE, _JSON_BODY_ERROR_ENVELOPE

_STEP = {
    "type": "object",
    "properties": {
        "do": {"type": "string", "enum": ["wait", "key_down", "key_up", "tap", "mouse_down", "mouse_up",
                                          "click", "move", "move_to", "scroll"]},
        "key": {"type": "string"},
        "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
        "ms": {"type": "integer", "description": "wait: duration. tap, click: length of the press. move: spread."},
        "dx": {"type": "integer"}, "dy": {"type": "integer"},
        "x": {"type": "integer"}, "y": {"type": "integer"},
        "clicks": {"type": "integer"},
    },
    "required": ["do"],
}
# The 400 names the step it refused; a body that is not an object adds `received`.
_BAD_REQUEST = {**_JSON_BODY_ERROR_ENVELOPE, "properties": {
    **_JSON_BODY_ERROR_ENVELOPE["properties"],
    "step": {"type": "integer", "description": "Index of the step that was refused, when one was."},
}}


def _refusal(description: str, schema: dict | None = None) -> dict:
    return {"description": description, "content": {"application/json": {"schema": schema or _ERROR_ENVELOPE}}}


def sequence_path_item(title_guard: str, title_conflict: str) -> dict:
    """A fresh path item on every call: the builder's later passes edit operations in place."""
    return {"post": {
        "summary": "Run timed input steps: hold keys and buttons, move by a delta, scroll, wait",
        "tags": ["Desktop"],
        "requestBody": {"content": {"application/json": {"schema": {
            "type": "object",
            "properties": {
                "steps": {"type": "array", "minItems": 1, "maxItems": 200, "items": _STEP},
                "require_active_title": {"type": "string", "description": title_guard},
            },
            "required": ["steps", "require_active_title"],
        }}}},
        "responses": {
            "200": {"description": "Every step ran; whatever was still held has been released"},
            "400": _refusal("A step is malformed or over a limit, require_active_title is missing, "
                            "or the body is not an object", _BAD_REQUEST),
            "403": _refusal("Desktop control was paused or revoked; held input has been released"),
            "409": _refusal(title_conflict),
            "500": _refusal("The system refused an input event; held input has been released"),
            "501": _refusal("No input driver for this desktop (native Windows only for now)"),
        },
    }}
