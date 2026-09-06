"""Parsing a number that a caller supplied, without trusting it.

`safe_int` and `safe_float` (v4.44.0) were in `handler_helpers`, which meant
`handler_params` -- the module that turns a bad number into a 400 -- had to
import from it, while `handler_helpers` re-exports `handler_params` for the
call sites that predate the split. Importing `arena.handler_params` first
then failed with a partially initialised module: three reviewers on the #270
PR reported it, and it made the new module unusable on its own.

The parsers have no dependencies of their own, so they live here and both
sides import downwards. `handler_helpers` re-exports them, as before.
"""
from __future__ import annotations

from typing import Any

__all__ = ["safe_float", "safe_int"]


_NO_DEFAULT = object()


def safe_float(
    value: Any,
    *,
    default: float | object = _NO_DEFAULT,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    """Parse a caller-supplied value into a bounded, finite float.

    v4.44.0 security-hardening helper. Every HTTP handler that
    coerces a query-string or JSON-body value into ``float`` used
    to be a copy of::

        try:
            x = float(request.query.get("timeout", "1.5"))
        except (TypeError, ValueError):
            x = 1.5

    That pattern is unsafe against two attacker-controlled shapes
    that semgrep (``nan-injection``) rightly complains about:

    * ``float("nan")`` -- passes through
      ``try/except (TypeError, ValueError)`` because ``NaN`` is a
      valid float. Downstream comparisons (``if x >= 0``) return
      ``False`` for both branches, so guard clauses relying on
      ordering silently break. In our case
      ``socket.settimeout(nan)`` raises ``ValueError`` server-side
      and turns a benign probe into a 500, which is a small
      availability hit -- but nan-in-comparison bugs elsewhere
      could bypass upper bounds.
    * ``float("inf")`` -- similar. Passes the ``try/except`` and
      then either loops forever, raises deep inside a syscall
      (``ValueError: timestamp out of range for platform time_t``),
      or converts to an overflow later.

    The safe pattern is: parse, reject NaN/Inf, optionally clamp
    to a ``[minimum, maximum]`` range. Everything else falls back
    to the caller-supplied default (or raises ``ValueError`` if
    the caller wanted strict).

    Args:
      value: any input, typically a query-string value.
      default: value to return on parse failure. Omit to make the
        function raise ``ValueError`` on any bad input.
      minimum, maximum: inclusive bounds. Out-of-range values are
        clamped when a ``default`` is provided; otherwise raise.

    Returns:
      A finite float, either the parsed value clamped into
      ``[minimum, maximum]`` or ``default``.
    """
    try:
        x = float(value)
    except (TypeError, ValueError):
        if default is _NO_DEFAULT:
            raise
        return default  # type: ignore[return-value]
    # NaN and +/-Inf are both "valid floats" per Python's float()
    # but almost never what an HTTP caller legitimately means.
    # Reject both.
    if x != x or x in (float("inf"), float("-inf")):
        if default is _NO_DEFAULT:
            raise ValueError(f"non-finite float rejected: {value!r}")
        return default  # type: ignore[return-value]
    if minimum is not None and x < minimum:
        if default is _NO_DEFAULT:
            raise ValueError(f"below minimum {minimum}: {x}")
        # Clamp to the boundary rather than falling to the default;
        # a request for "timeout=0.001" against min=0.01 is closer
        # to "operator meant fast" than "operator meant default".
        return float(minimum)
    if maximum is not None and x > maximum:
        if default is _NO_DEFAULT:
            raise ValueError(f"above maximum {maximum}: {x}")
        return float(maximum)
    return x


def safe_int(
    value: Any,
    *,
    default: int | object = _NO_DEFAULT,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    """Parse a caller-supplied value into a bounded int.

    v4.44.0 companion to :func:`safe_float`. Same clamp/default
    semantics. Not vulnerable to NaN/Inf (Python's ``int()`` rejects
    both), but still worth centralising because HTTP inputs also
    like to send negative "timeout" or "limit" values that break
    downstream ``range()`` / ``head[:n]`` slicing invariants.
    """
    try:
        x = int(value)
    except (TypeError, ValueError):
        if default is _NO_DEFAULT:
            raise
        return default  # type: ignore[return-value]
    if minimum is not None and x < minimum:
        if default is _NO_DEFAULT:
            raise ValueError(f"below minimum {minimum}: {x}")
        return int(minimum)
    if maximum is not None and x > maximum:
        if default is _NO_DEFAULT:
            raise ValueError(f"above maximum {maximum}: {x}")
        return int(maximum)
    return x
