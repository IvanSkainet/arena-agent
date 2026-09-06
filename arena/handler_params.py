"""Reading a number out of a request, and refusing the ones that are not.

Two helpers, one rule: a value the caller supplied and got wrong is a 400
naming the field, never a 500 naming a Python builtin. `query_int` landed
with #254 for query strings, `body_int` with #270 for JSON bodies, and they
live here rather than in `handler_helpers` because that module hit the
600-line ceiling in `test_architecture_boundaries.py` -- the same reason the
error classes moved out in #266. `handler_helpers` re-exports both, so every
existing import keeps working.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, overload

from aiohttp import web

from arena.handler_errors import BodyFieldError, QueryParamError
from arena.handler_helpers import safe_int

__all__ = ["body_int", "body_str", "query_int"]


def query_int(
    request: web.Request, name: str, *, default: int | None,
) -> int | None:
    """Read an integer query parameter, or refuse the request with a 400.

    ``safe_int`` (v4.44.0) already did the parsing. What it could not decide
    is what a *handler* should do with a bad value, and both of the answers
    it offers are wrong on their own:

    * ``safe_int(raw, default=50)`` swallows the mistake. A client sending
      ``?limit=fifty`` gets 200 and the first fifty rows, and goes on sending
      ``fifty`` forever because nothing ever told it otherwise.
    * ``safe_int(raw)`` raises ``ValueError``, which the wrappers above turn
      into ``500 {"error": "ValueError: invalid literal for int() ...",
      "error_type": "ValueError"}`` -- the bridge blaming itself for the
      caller's typo, and naming an internal Python class while doing it.
      That is #254, measured live on the operator's bridge at v4.170.0.

    So: parse strictly, and re-raise the failure as :class:`QueryParamError`,
    which the decorators answer with 400.

    A missing or empty parameter is not an error. ``?offset=`` means
    "unspecified" and yields ``default``, which is what it did before -- the
    old ``int(query.get("offset", [0])[0] or 0)`` reached ``int()`` only for
    a non-empty value too. Only the parse verdict changes, never the value
    of a request that already worked.

    Deliberately no ``minimum``/``maximum``: every current caller passes its
    bad values on to a layer that already clamps them (``?limit=-1`` answers
    200 with ``limit: 1`` today), and turning those into refusals would be a
    behaviour change riding along with a bug fix. ``safe_int`` still has the
    bounds for callers that genuinely need them.

    Args:
      request: the live aiohttp request.
      name: query-string key, named in the error so the caller can fix it.
      default: value for a missing or empty parameter. Keyword-only and
        required -- pass ``None`` for a genuinely optional one, so that
        "I forgot a default" cannot pass for "there is none".

    Raises:
      QueryParamError: the parameter was supplied and does not parse.
    """
    raw = request.query.get(name)
    if raw is None or raw == "":
        return default
    try:
        return safe_int(raw)
    except (TypeError, ValueError):
        raise QueryParamError(name) from None


@overload
def body_int(body: Mapping[str, Any], name: str, *, default: int,
             bounds: tuple[int, int] | None = None) -> int: ...


@overload
def body_int(body: Mapping[str, Any], name: str, *, default: None,
             bounds: tuple[int, int] | None = None) -> int | None: ...


def body_int(
    body: Mapping[str, Any], name: str, *, default: int | None,
    bounds: tuple[int, int] | None = None,
) -> int | None:
    """Read an integer field out of a JSON body, or refuse with a 400.

    #254 fixed this for query strings and #270 measured the same defect one
    layer over: thirteen documented (operation, field) pairs answered
    ``500 {"error": "TypeError: int() argument must be ... not 'list'",
    "error_type": "TypeError"}`` to a body a client can send by accident.
    The status blamed the bridge for the caller's mistake and the envelope
    named a Python builtin, which #254 and #259 both spent tests pinning as
    absent everywhere else.

    A body field is not a query parameter, and the difference decides the
    rules here:

    * It arrives already typed, so `true`, `[]` and `{}` are refusals rather
      than parse attempts. `int(True)` is 1 and would have quietly accepted
      a boolean where a count was meant.
    * A float has to be decided rather than inherited. ``2.0`` is the same
      number as ``2`` and languages without an integer type send it that
      way, so it is accepted; ``2.5`` is a different number and is refused,
      where ``int()`` would have silently truncated it to 2.
    * A string still parses, because callers send ``"10"`` today and this is
      a bug fix, not a tightening. It goes through ``safe_int``, so it
      inherits the #254 verdicts: ``" 1"`` is 1, ``"abc"`` is a refusal.

    Missing, ``None`` and ``""`` all mean "unspecified" and yield *default*,
    matching both ``query_int`` and the ``int(body.get(x, 20) or 20)`` idiom
    this replaces -- so no request that works today starts failing.

    `bounds` exists for one reason and is off by default. `query_int`
    deliberately has no bounds -- every caller passed its value to a layer
    that already clamped it -- but a body number can reach a system call
    directly: `{"timeout": 1578655390615}` on `/v1/mission/run` came back as
    `OverflowError: timestamp too large to convert to C PyTime_t`, a 500 for
    an integer that is perfectly valid JSON. Where that is possible the
    handler says so, and the refusal names the bound rather than repeating
    "must be an integer" at someone who sent one. `{"timeout": -174294}` is
    the same defect with the sign flipped.

    Args:
      body: the parsed JSON object.
      name: field name, named in the error so the caller can fix it.
      default: value for an unspecified field. Keyword-only and required;
        pass ``None`` for a genuinely optional one.
      bounds: `(minimum, maximum)` for values that end up in a system call.
        Omit unless a number outside some range can break something.

    Raises:
      BodyFieldError: the field was supplied and is not an integer, or
        falls outside `bounds`.
    """
    parsed = _parse_body_int(body, name)
    if parsed is _UNSPECIFIED:
        return default
    number = int(parsed)  # type: ignore[arg-type]
    if bounds is not None:
        _check_bounds(name, body.get(name), number, bounds)
    return number


def _check_bounds(name: str, raw: object, number: int,
                  bounds: tuple[int, int]) -> None:
    """Refuse a number outside the range, naming the end it went past."""
    minimum, maximum = bounds
    if number < minimum:
        raise BodyFieldError(
            name, raw, expected=f"an integer no smaller than {minimum}")
    if number > maximum:
        raise BodyFieldError(
            name, raw, expected=f"an integer no greater than {maximum}")


_UNSPECIFIED = object()


def _parse_body_int(body: Mapping[str, Any], name: str) -> object:
    """The type work, split out so `body_int` reads as one decision.

    Returns `_UNSPECIFIED` for a field the caller did not set, so that a
    genuine `0` is not confused with "missing" the way a falsy check would.
    """
    value = body.get(name)
    if value is None or value == "":
        return _UNSPECIFIED
    # `bool` first: it is a subclass of `int`, so the check below would
    # accept `true` as 1. Anything outside these three types cannot be a
    # number however it is read.
    if isinstance(value, bool) or not isinstance(value, int | float | str):
        raise BodyFieldError(name, value)
    return _number_from(name, value)


def _number_from(name: str, value: int | float | str) -> int:
    """int, whole float or numeric string -- or a refusal."""
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise BodyFieldError(name, value)
    try:
        return safe_int(value)
    except (TypeError, ValueError):
        raise BodyFieldError(name, value) from None


def body_str(body: Mapping[str, Any], name: str, *, default: str) -> str:
    """Read a string field out of a JSON body, or refuse with a 400.

    The string counterpart of `body_int`, added for the same reason and
    found the same way. `str()` accepts anything, so `{"cwd": {...}}` on
    /v1/exec became a path made of the repr of a dict, and `Path.exists()`
    answered `OSError: [Errno 36] File name too long` -- a 500 where "cwd
    must be a string" was the whole of it (#270).

    Numbers and booleans are refused rather than stringified: `{"cwd": 12}`
    is a caller mistake, and turning it into the directory "12" hides it.
    Missing and null mean unspecified, as everywhere else here.
    """
    value = body.get(name)
    if value is None:
        return default
    if not isinstance(value, str):
        raise BodyFieldError(name, value, expected="a string")
    return value
