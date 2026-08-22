"""Timing-safe secret comparison that cannot be crashed by its input.

`hmac.compare_digest` accepts `str`, but only if *both* operands are
pure ASCII -- otherwise it raises::

    TypeError: comparing strings with non-ASCII characters is not supported

Every credential the bridge compares arrives from the network: an
`Authorization` header, a `?token=` query parameter, an acknowledgement
string in a JSON body. An attacker therefore controls one operand and
can pick a non-ASCII one at will. Calling `hmac.compare_digest` on those
strings directly turns an unauthenticated request into an unhandled
`TypeError`, which the error middleware reports as HTTP 500.

Measured against the live bridge before this module existed::

    GET /v1/status  Authorization: Bearer <u-umlaut>        -> 500
    GET /v1/status  Authorization: Bearer agent-<uml>-attack -> 500
    GET /gui?token=%C3%BC                                    -> 500
    GET /v1/status  Authorization: Bearer agent-deadbeef-... -> 401

So the failure was reachable with no credential at all, on both the API
and the GUI login route: an unauthenticated error-response amplifier,
and a liveness bug on paths whose whole job is to answer 401.

Comparing UTF-8 *bytes* has neither problem. `compare_digest` on
`bytes` is defined for every input, so the comparison stays timing-safe
and total. Length still leaks -- that is inherent to `compare_digest`
and unchanged here.
"""
from __future__ import annotations

import hmac

__all__ = ["secrets_equal"]


def secrets_equal(presented: object, expected: object) -> bool:
    """Return whether two secrets match, in constant time, without raising.

    Accepts `str` or `bytes` on either side and encodes `str` as UTF-8
    before comparing, so non-ASCII input is answered with `False`
    instead of a `TypeError`. Anything that is neither `str` nor `bytes`
    (`None`, a dict decoded from JSON, ...) is not a secret and compares
    `False` rather than crashing the caller.
    """
    left = _as_bytes(presented)
    right = _as_bytes(expected)
    if left is None or right is None:
        return False
    return hmac.compare_digest(left, right)


def _as_bytes(value: object) -> bytes | None:
    if isinstance(value, bytes):
        return value
    if isinstance(value, str):
        # surrogatepass: a header that survived latin-1 decoding can hold
        # lone surrogates, and a plain .encode("utf-8") would raise on
        # those -- reintroducing the very crash this module removes.
        return value.encode("utf-8", "surrogatepass")
    return None
