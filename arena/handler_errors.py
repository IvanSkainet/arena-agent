"""The caller mistakes the handler decorators answer with a 400.

Three classes and a lookup table, moved out of `handler_helpers` because
that module hit the 600-line ceiling in `test_architecture_boundaries.py`
and because they are a coherent group: they describe *what the caller got
wrong*, and nothing in them knows about decorators, contexts or responses.
`handler_helpers` re-exports all three, so every existing import keeps
working (#266).
"""
from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

__all__ = ["BadRequest", "BodyFieldError", "JsonBodyError", "QueryParamError"]


# "the body could not be read as JSON at all", distinct from any JSON value
# a caller might legitimately have sent -- including None.
_UNREADABLE = object()


class BadRequest(ValueError):
    """Base for the caller mistakes the decorators below answer with a 400.

    A handler raises one of these instead of returning a response, so the
    refusal is written once, in the wrapper, rather than copy-pasted at every
    call site -- which is how the copies drifted apart in the first place
    (#254, #259).

    Subclassing ``ValueError`` is deliberate: a handler that already wrote
    ``except ValueError:`` around its own parsing keeps the behaviour it has
    today when it adopts one of these helpers.
    """

    #: Extra machine-readable fields for the envelope. Read-only: a bare
    #: `{}` is one dict shared by every instance that does not set its own,
    #: so an in-place write would leak into the next request.
    details: Mapping[str, Any] = MappingProxyType({})


class QueryParamError(BadRequest):
    """A query parameter was present but could not be parsed (#254).

    Raised by :func:`query_int`. The handler decorators in this module
    translate it into a 400 naming the parameter, instead of letting it
    reach the generic ``except Exception`` and become a 500.

    Carries the parameter *name*, not the offending value: the name is the
    part of the pair the caller has to fix, and echoing an attacker-supplied
    value back into a response body turns a JSON error envelope into a
    reflection gadget.
    """

    def __init__(self, param: str) -> None:
        self.param = param
        self.details = {"param": param}
        super().__init__(f"query parameter {param!r} must be an integer")


# Every JSON type `json.loads` can produce except the object we wanted.
# The document repeats this list as an enum, and a test compares the two.
_JSON_TYPE_NAMES: dict[type, str] = {
    type(None): "null", bool: "boolean", int: "number",
    float: "number", str: "string", list: "array",
}


class JsonBodyError(BadRequest):
    """The request body is not the JSON object this endpoint reads (#259).

    Names the JSON *type* that arrived, never the value. The type is one of
    five fixed words and tells the caller exactly what to change; the value
    is attacker-controlled text that has no business being reflected back
    out of an error envelope, into a log line or onto a dashboard.

    `received` is absent in two cases, which is why the document marks it
    optional: when nothing parsed at all -- there is no JSON type to name,
    and inventing `null` would tell a client the body was JSON null when it
    was truncated bytes -- and when a custom decoder produced something
    outside the five. The second is unreachable through `json.loads` and is
    handled rather than asserted, because a 500 from an error path is a
    poor way to find out otherwise.
    """

    def __init__(self, received: object = _UNREADABLE) -> None:
        if received is _UNREADABLE:
            self.received = None
            super().__init__("request body must be valid JSON")
            return
        self.received = _JSON_TYPE_NAMES.get(type(received))
        if self.received is None:
            super().__init__("request body must be a JSON object")
            return
        self.details = {"received": self.received}
        super().__init__(
            f"request body must be a JSON object, received {self.received}")


# The body counterpart adds the one type #259 has no use for: an object is
# exactly what that check wanted, so it never had to name it, while a field
# inside the object can perfectly well be one.
_BODY_TYPE_NAMES: dict[type, str] = {**_JSON_TYPE_NAMES, dict: "object"}


class BodyFieldError(BadRequest):
    """A field in the JSON body is not the integer this endpoint reads (#270).

    The body counterpart of :class:`QueryParamError`, and it can say one
    thing that one cannot: a query string is text, so the only fault
    available is "does not parse", while a body field arrives already typed
    and can be an array where a number was meant. Naming the JSON type turns
    "must be an integer" into a sentence the caller can act on without
    guessing which of their fields the server disliked.

    Same rule as #259 on what goes in the envelope: the field name and the
    JSON type, never the value. The name is the half the caller has to fix,
    and reflecting attacker-supplied text out of an error body is how an
    error envelope becomes a gadget.
    """

    def __init__(self, field: str, received: object = _UNREADABLE,
                 *, expected: str = "an integer") -> None:
        self.field = field
        self.received = (None if received is _UNREADABLE
                         else _BODY_TYPE_NAMES.get(type(received)))
        self.details = ({"field": field} if self.received is None
                        else {"field": field, "received": self.received})
        # `expected` carries the bound when there is one: "an integer no
        # greater than 86400" is the whole answer, where "must be an integer"
        # sent to someone who did send an integer is a riddle.
        tail = "" if self.received is None else f", received {self.received}"
        super().__init__(f"body field {field!r} must be {expected}{tail}")
