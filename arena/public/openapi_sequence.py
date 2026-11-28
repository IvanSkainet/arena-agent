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
        "dx": {"type": "integer", "description": "move: mouse counts, as a device reports them. The desktop "
               "cursor follows at the system pointer speed; a program reading raw input gets the counts as they are."},
        "dy": {"type": "integer"},
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


_RELEASE = ("The runner then tries to release everything it was holding; `release_failed` lists any key or "
            "button the system would not let go, which may still be down.")


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
            "200": {"description": "Every step ran, and everything still held was released"},
            "400": _refusal("A step is malformed or over a limit, require_active_title is missing, "
                            "or the body is not an object", _BAD_REQUEST),
            "403": _refusal("Desktop control was paused or revoked during the run. " + _RELEASE),
            "409": _refusal(title_conflict + ". " + _RELEASE + " Also returned, with error "
                            "`sequence_in_progress` and nothing sent, while another sequence is still running: "
                            "one sequence drives the desktop at a time."),
            "500": _refusal("The system refused an input event (`input_failed`), or a limit was passed during "
                            "the run (`input_overran`): the limits are checked on the plan and again on the "
                            "clock while it runs, where a key down for more than 17 s or a run of more than "
                            "47 s stops the sequence at its next check. " + _RELEASE),
            "501": _refusal("No input driver for this desktop (native Windows only for now)"),
        },
    }}
