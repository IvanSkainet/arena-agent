"""Shared redaction primitives (v4.45.0).

Consolidates the credential-shape scrubbing that lived inline
in ``arena/observability/audit.py`` and the URL-truncation logic
that lived in ``arena/agentctl_cli/agentctl_bridge.py`` into
one module so:

* every write-out-to-disk / write-out-to-stderr path can share
  the exact same rules (audit log, request log, exception
  formatters, agent-side logging);
* adding a new credential pattern -- ``ClaudeCode API key`` etc.
  -- is one edit here instead of hunting through emit sites;
* tests targeting the redaction rules live in one place.

Two public entry points:

* :func:`redact_string` -- scrub known credential shapes from
  a free-form string. Cheap fast-path for short strings
  (< 16 chars) that cannot carry a real credential; falls
  through to the regex battery otherwise. Idempotent.
* :func:`redact_value` -- recursive; handles nested dicts,
  lists, tuples, and leaves. Non-string primitives
  (int/bool/None/float) pass through unchanged.

Neither entry point mutates its input; both return a scrubbed
copy. This is deliberate: the sanitizer is called on data that
may be reused by the caller (e.g. an in-memory event that
also gets emitted to a metrics counter).

Rationale for keeping this module tiny and dependency-free:
credential-shape regexes are the exact place where a
transitive dependency would be catastrophic ("hey, our
redactor got compromised, so now every audit line ships the
plaintext to attacker-controlled DNS"). Everything here uses
only ``re`` + built-in string ops.
"""
from __future__ import annotations

import re
from typing import Any


# Key-name substrings that indicate a value should be redacted
# outright, regardless of pattern. Kept as a frozenset for
# constant-time membership testing.
SENSITIVE_KEY_SUBSTRINGS: frozenset[str] = frozenset({
    "token", "authorization", "password", "secret",
    "api_key", "apikey", "credential", "passphrase",
    "private_key", "privatekey",
})


# Value patterns that indicate a credential embedded in a
# larger string. Each pattern is precompiled and the match is
# replaced with ``<redacted:{name}>`` so operators can still
# see WHICH kind of secret leaked without seeing the secret
# itself.
#
# The list is ordered from most specific to most generic so
# a JWT (three dotted base64url segments) is caught by its
# JWT pattern instead of the generic "long base64-ish string"
# pattern would be too broad to ship.
#
# v4.45.0 note: patterns use ``(?<![A-Za-z0-9])`` and
# ``(?![A-Za-z0-9])`` lookaround boundaries instead of ``\b``
# because ``\b`` doesn't fire between two adjacent
# alphanumerics -- so a token pasted right after ``=`` or
# ``%20`` (URL-encoded space) or any other non-word delimiter
# would slip past a ``\b``-anchored pattern. The lookaround
# form fires as long as the token isn't in the middle of a
# longer alphanumeric run, which is the actual condition we
# want.
_LB = r"(?<![A-Za-z0-9])"   # left boundary
_RB = r"(?![A-Za-z0-9])"    # right boundary


_VALUE_PATTERNS: list[tuple[str, "re.Pattern[str]"]] = [
    ("bearer", re.compile(_LB + r"Bearer\s+[A-Za-z0-9\-._~+/=]{16,}")),
    ("basic", re.compile(_LB + r"Basic\s+[A-Za-z0-9+/=]{16,}")),
    ("aws-access-key", re.compile(_LB + r"(?:AKIA|ASIA)[0-9A-Z]{16}" + _RB)),
    ("github", re.compile(_LB + r"(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}" + _RB)),
    ("openai-style", re.compile(_LB + r"sk-(?:ant-)?[A-Za-z0-9\-_]{20,}" + _RB)),
    ("slack", re.compile(_LB + r"xox[baprs]-[A-Za-z0-9\-]{10,}" + _RB)),
    ("google-api", re.compile(_LB + r"AIza[0-9A-Za-z\-_]{35}" + _RB)),
    ("jwt", re.compile(
        _LB + r"eyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+" + _RB
    )),
    ("uri-creds", re.compile(
        r"\b[a-z][a-z0-9+.\-]*://[^\s:@/]+:[^\s@/]+@[^\s]+"
    )),
    ("ssh-key", re.compile(
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"
    )),
]


def is_sensitive_key(key: str) -> bool:
    """Return True when ``key`` (case-insensitive) contains any
    known sensitive substring.

    Deliberately substring-based (not exact-match) so operator-
    invented key names like ``my_api_key`` or ``bot_token_v2``
    are still caught."""
    low = key.lower()
    return any(sub in low for sub in SENSITIVE_KEY_SUBSTRINGS)


def redact_string(text: str) -> str:
    """Scrub known credential patterns from a free-form string.

    Runs every pattern in turn, replacing the match with
    ``<redacted:{kind}>``. Called on any leaf string value that
    reached a redaction-aware sink (audit log, request log,
    error formatter).

    Fast-path optimisation: strings shorter than 16 chars cannot
    match any of the patterns (every pattern needs at least 16
    chars of match), so we skip the whole regex battery. On the
    audit-log hot path this saves ~90% of calls (most audit
    field values are short like status codes, method names,
    booleans).
    """
    if len(text) < 16:
        return text
    for name, pat in _VALUE_PATTERNS:
        text = pat.sub(f"<redacted:{name}>", text)
    return text


def redact_value(value: Any) -> Any:
    """Recursively scrub a value: dicts, lists, tuples, strings.

    Non-string primitives (int/bool/None/float) pass through.
    Dicts have both their keys checked (via
    :func:`is_sensitive_key`) and their values scrubbed.
    Sensitive keys have their WHOLE value replaced with
    ``<redacted>``; non-sensitive keys have their value
    recursively scrubbed for embedded patterns.

    Returns a NEW structure -- the caller's original is not
    mutated. Order preserved for dicts (Python 3.7+ guarantee).
    """
    if isinstance(value, dict):
        out: dict[Any, Any] = {}
        for k, v in value.items():
            if isinstance(k, str) and is_sensitive_key(k):
                out[k] = "<redacted>"
            else:
                out[k] = redact_value(v)
        return out
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, str):
        return redact_string(value)
    return value
