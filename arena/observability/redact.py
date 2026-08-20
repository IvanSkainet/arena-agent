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
import threading
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


_VALUE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("bearer", re.compile(_LB + r"Bearer\s+[A-Za-z0-9\-._~+/=]{16,}")),
    ("basic", re.compile(_LB + r"Basic\s+[A-Za-z0-9+/=]{16,}")),
    # v4.170.0 (#132): the bridge's own auth headers. `Bearer` above
    # only fires on the Authorization spelling; a curl carrying
    # `X-Arena-Token: <token>` left the value in the clear. Matched
    # by header name so it works for any token value, including one
    # this process does not know (e.g. a peer bridge's).
    ("arena-token-header", re.compile(
        r"(?i)X-Arena-Token\s*[:=]\s*[A-Za-z0-9\-._~+/=]{12,}"
    )),
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
    # --- generic, LAST on purpose ------------------------------------
    # The two below match by *context* (a credential-ish name next to a
    # long value) rather than by the value's own shape, so they would
    # also swallow `token=ghp_...` and report it as a mere assignment.
    # A marker is not cosmetic: an operator reading the audit uses it to
    # decide which credential to rotate and where the leak came from, so
    # the specific patterns above must claim their matches first.
    #
    # `--token <v>` / `--token=<v>` on a command line. The bridge's own
    # CLI takes the master token this way (`arena serve --token ...`), so
    # an audited command that starts or manages a *peer* bridge -- whose
    # token this process cannot have registered -- leaked it verbatim.
    # First among the context patterns: `--token=<v>` also satisfies the
    # generic assignment pattern below, and the specific marker is the
    # one an operator needs to know which credential to rotate.
    ("cli-credential-option", re.compile(
        r"(?i)--(?:token|api[-_]?key|secret|password|passphrase)"
        + r"(?:\s+|=)[\"']?[A-Za-z0-9\-._~+/=%]{12,}"
    )),
    # `?token=` / `&api_key=` in a recorded URL. The bridge accepts a
    # query-string token (deprecated but live), so a recorded command
    # that used one leaked it verbatim. Ordered before the assignment
    # pattern, which also matches `?token=<v>`.
    #
    # `%` belongs in the value class: the query path percent-decodes
    # before comparing, so `?token=correct%20horse%20battery%20staple`
    # authenticates as `correct horse battery staple`. Literal
    # substitution searches for the *decoded* secret and cannot see the
    # encoded spelling -- only this pattern can.
    ("query-credential", re.compile(
        r"(?i)[?&](?:token|api_key|apikey|access_token|secret)"
        + r"=[A-Za-z0-9\-._~+/=%]{12,}"
    )),
    # Shell/env assignment of a known-secret variable name, e.g.
    # `BRIDGE_TOKEN=...` or `ARENA_BRIDGE_TOKEN=...` in a command line.
    ("token-assignment", re.compile(
        r"(?i)(?<![A-Za-z0-9_])[A-Za-z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY)"
        + r"\s*=\s*[\"']?[A-Za-z0-9\-._~+/=%]{12,}"
    )),
]


# v4.170.0 (#132): shape patterns cannot catch the bridge's own
# bearer. It is 43 characters of unstructured base62 -- no prefix,
# no separator, no checksum -- so every pattern above misses it,
# and a generic "long alphanumeric run" pattern would redact
# commit SHAs, base64 payloads and file hashes across the whole
# audit log. The only reliable discriminator is the value itself,
# which this process knows.
#
# Registered literals are matched verbatim, before the shape
# patterns run, so a token that also happens to sit behind
# ``Bearer `` is reported as the specific secret it is.
#
# Membership is kept in a module-level set rather than passed in
# per call because the emit sites (audit, request log, error
# formatters) are spread across the codebase and threading a
# config object through all of them is exactly the kind of change
# that gets partially applied. Registration is idempotent.
_LITERAL_SECRETS: dict[str, str] = {}

#: Mutations are rare (startup, rotation); reads are on the audit hot
#: path and come from executor threads. Iterating the dict directly
#: raised ``RuntimeError: dictionary changed size during iteration``
#: when a ``token_regenerate`` rotation landed mid-log -- i.e. exactly
#: when the audit record mattered most. Readers take one atomic
#: attribute load of an immutable snapshot instead of locking; the lock
#: serialises writers only.
_LITERAL_LOCK = threading.Lock()
_LITERAL_SNAPSHOT: tuple[tuple[str, str], ...] = ()

#: Below this length a literal is too short to register: a value
#: like "1" or "dev" would redact unrelated text everywhere. The
#: bridge's token is 43 chars; agent tokens are longer.
LITERAL_MIN_LENGTH = 12


def _rebuild_literal_snapshot() -> None:
    """Republish the immutable read snapshot. Caller must hold the lock.

    Longest first: a token that contains a shorter registered literal as
    a substring must be reported as itself, not left half-substituted.
    """
    global _LITERAL_SNAPSHOT
    _LITERAL_SNAPSHOT = tuple(
        sorted(_LITERAL_SECRETS.items(), key=lambda kv: len(kv[0]), reverse=True)
    )


def register_literal_secret(value: str, kind: str = "bridge-token") -> bool:
    """Register an exact string to scrub from every redacted sink.

    Returns True when the value was registered. Short, empty and
    non-string values are rejected rather than silently ignored so
    a caller passing a missing config key cannot believe it is
    protected -- and so registering ``""`` cannot turn every
    string into a redaction.
    """
    if not isinstance(value, str):
        return False
    candidate = value.strip()
    if len(candidate) < LITERAL_MIN_LENGTH:
        return False
    with _LITERAL_LOCK:
        _LITERAL_SECRETS[candidate] = kind
        _rebuild_literal_snapshot()
    return True


def unregister_literal_secret(value: str) -> None:
    """Drop a previously registered literal (used after rotation)."""
    if isinstance(value, str):
        with _LITERAL_LOCK:
            _LITERAL_SECRETS.pop(value.strip(), None)
            _rebuild_literal_snapshot()


def registered_literal_count() -> int:
    """Number of registered literals. For tests and diagnostics.

    Deliberately does not expose the values: a diagnostic endpoint
    that dumped them would recreate the leak this closes.
    """
    return len(_LITERAL_SECRETS)


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

    v4.170.0 (#132): registered literals are substituted first and
    are NOT subject to the 16-char fast path, because the fast
    path's premise -- "nothing shorter can be a credential" --
    only holds for the shape patterns. A registered literal is
    known to be a credential at any length above
    ``LITERAL_MIN_LENGTH``. The scan reads an immutable snapshot,
    so a rotation on another thread cannot make it raise.
    """
    # One atomic load; the tuple it names can never be mutated, so a
    # rotation on another thread cannot make this loop raise. Iterating
    # an empty tuple is cheaper than any length guard would be, so the
    # 16-char fast path below is deliberately NOT applied to literals.
    for secret, kind in _LITERAL_SNAPSHOT:
        if secret in text:
            text = text.replace(secret, f"<redacted:{kind}>")
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
