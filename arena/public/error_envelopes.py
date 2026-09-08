"""The JSON error bodies every operation in the document can return.

Split out of `openapi.py` because they are the shape of a refusal, not the
list of paths: the document module stayed under the architecture line-count
gate only by carrying them, and a reader looking for "what does a 400 look
like" should not have to scroll past 60 endpoints to find out.
"""
from __future__ import annotations

_ERROR_ENVELOPE = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean", "enum": [False]},
        "error": {"type": "string"},
        "request_id": {"type": "string"},
    },
    "required": ["ok", "error"],
}


# The parse-failure 400 carries one field the universal envelope does not:
# the name of the parameter that failed. A generated client can highlight
# that field; a client reading only `error` has to parse English.
_QUERY_PARAM_ERROR_ENVELOPE = {
    "type": "object",
    "properties": {
        **_ERROR_ENVELOPE["properties"],
        "param": {
            "type": "string",
            "description": "Name of the query parameter that failed to parse.",
        },
    },
    "required": ["ok", "error", "param"],
}


# The other refusal that names its cause: a body that parsed as JSON but is
# not an object. `received` carries the JSON type that arrived -- one of five
# fixed words, never the value the caller sent.
_JSON_BODY_ERROR_ENVELOPE = {
    "type": "object",
    "properties": {
        **_ERROR_ENVELOPE["properties"],
        "received": {
            "type": "string",
            "enum": ["null", "boolean", "number", "string", "array"],
            "description": (
                "The JSON type of the body that arrived. Absent when the "
                "body did not parse as JSON at all, since then there is no "
                "type to name."),
        },
    },
    # `received` is deliberately not required: the same 400 also answers a
    # body that is not JSON at all, and promising a field that arrives only
    # sometimes is the same untruth as omitting one that always does.
    "required": ["ok", "error"],
}


# The body-field refusal (#270). `field` is always there -- the parse either
# failed on a named field or did not happen -- and `received` names the JSON
# type that arrived. Six words here rather than the five above: a field
# inside the object can be an object, which is exactly what the body-shape
# check was looking for and so never had to name.
_BODY_FIELD_ERROR_ENVELOPE = {
    "type": "object",
    "properties": {
        **_ERROR_ENVELOPE["properties"],
        "field": {
            "type": "string",
            "description": ("Name of the body field whose value has the wrong "
                            "type -- a number field that got something "
                            "other than a number, and so on."),
        },
        "received": {
            "type": "string",
            "enum": ["null", "boolean", "number", "string", "array", "object"],
            "description": "The JSON type of the value that arrived.",
        },
    },
    "required": ["ok", "error", "field"],
}


# The third refusal that names its cause, and the only 5xx that does: the
# machine has no tool for this. `unavailable` lists what to install -- any
# one of them is enough -- so a client can say "install tesseract" instead of
# reading the sentence (#260).
_UNAVAILABLE_ENVELOPE = {
    "type": "object",
    "properties": {
        **_ERROR_ENVELOPE["properties"],
        "unavailable": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": (
                "The tools blocking this call right now, in the order the "
                "bridge prefers them: installing any one of these clears "
                "this particular blocker. It does not promise the call then "
                "succeeds -- an operation built on several tools (OCR reads "
                "a screenshot before it reads text) reports one layer at a "
                "time, and the next call may name a tool from the next "
                "layer."),
        },
    },
    "required": ["ok", "error", "unavailable"],
}
