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

import math
from typing import Any

__all__ = ["safe_float", "safe_int"]


_NO_DEFAULT = object()


def _default_or_raise(default: Any) -> Any:
    """The shared "it did not parse" branch of both readers.

    Re-raises the exception being handled when the caller asked for strict
    parsing, which is why it is only ever called from inside an `except`.
    """
    if default is _NO_DEFAULT:
        raise
    return default


def _clamped(x: float, minimum: float | None, maximum: float | None,
             *, strict: bool) -> float:
    """`x` pulled inside `[minimum, maximum]`, or a refusal if strict.

    Strict means the caller gave no default and wants to hear about the
    range rather than have it silently applied.
    """
    if minimum is not None and x < minimum:
        return _at_bound(x, minimum, "below minimum", strict=strict)
    if maximum is not None and x > maximum:
        return _at_bound(x, maximum, "above maximum", strict=strict)
    return x


def _at_bound(x: float, limit: float, side: str, *, strict: bool) -> float:
    """The boundary value, or the ValueError the strict caller asked for."""
    if strict:
        raise ValueError(f"{side} {limit}: {x}")
    return limit


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
    except (TypeError, ValueError, OverflowError):
        # OverflowError as well: `float(10**400)` is "number too large to
        # convert", which reached /v1/game/boe/wait_inbox as a 500 (cubic).
        return _default_or_raise(default)
    # NaN and +/-Inf are both "valid floats" per Python's float() but almost
    # never what an HTTP caller legitimately means. `math.isfinite` covers
    # all three in one word; the previous spelling was `x != x or x in
    # (inf, -inf)`, which SonarCloud reads as a bug (S1764, identical
    # sub-expressions around `!=`) rather than as the NaN idiom it is.
    if not math.isfinite(x):
        # `default` is typed `float | object` only because `_NO_DEFAULT` is a
        # sentinel object; anything else there is a number the caller passed.
        # Narrowing with isinstance rather than a `# type: ignore`, which
        # AGENTS.md forbids (cubic), and a non-number default is treated as
        # no default rather than quietly becoming one.
        if isinstance(default, int | float) and not isinstance(default, bool):
            return float(default)
        raise ValueError(f"non-finite float rejected: {value!r}")
    # Clamp to the boundary rather than falling to the default; a request
    # for "timeout=0.001" against min=0.01 is closer to "operator meant
    # fast" than "operator meant default".
    return float(_clamped(x, minimum, maximum, strict=default is _NO_DEFAULT))


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
    except (TypeError, ValueError, OverflowError):
        # `int(float("inf"))` raises OverflowError, not ValueError, so an
        # infinity used to escape this function instead of falling back to
        # the default the caller supplied (cubic).
        return _default_or_raise(default)
    return int(_clamped(x, minimum, maximum, strict=default is _NO_DEFAULT))
