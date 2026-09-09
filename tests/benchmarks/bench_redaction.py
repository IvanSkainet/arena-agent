"""Benchmarks for the credential scrubber.

``arena.observability.redact`` sits on the write path of the audit log,
the request log and every error formatter: each of them calls
:func:`redact_value` on the whole record before it reaches disk. It is a
battery of a dozen regexes plus a literal scan, so it is the one piece of
pure-CPU work the bridge does on every single request.

The cases below are chosen to cover the three shapes that behave very
differently:

* a short value that takes the ``len(text) < 16`` fast path -- the
  majority of audit fields (status codes, method names, booleans);
* a long value with no credential in it, which pays for every pattern and
  matches none -- the worst case, and the common one;
* a value that actually carries a credential, where the substitution runs.

The registered-literal path is measured separately because it is the only
part that runs *before* the fast path and therefore costs something on
every call, however short.
"""
from __future__ import annotations

from arena.observability.redact import (
    is_sensitive_key,
    redact_string,
    redact_value,
    register_literal_secret,
    unregister_literal_secret,
)


def _shaped(prefix: str, alphabet: str, length: int) -> str:
    """A credential-SHAPED string, assembled rather than written down.

    The redactor matches on shape, so these benchmarks need values that
    look like credentials -- and a file full of literals that look like
    credentials makes every secret scanner in this repository's CI right
    about the file and wrong about the risk (gitleaks reads
    ``"x-arena-token": "<43 hex chars>"`` as a leak, and it is not wrong
    to). Silencing that with a path allowlist is exactly the fix #177
    rejected: a ``paths`` entry blinds the whole file to every rule, so a
    genuine credential added here later would be ignored.

    Assembling the value from a repeating alphabet keeps the runtime
    string the right shape and length while leaving nothing on disk that
    a scanner should ever have to judge.
    """
    body = (alphabet * (length // len(alphabet) + 1))[:length]
    return prefix + body


_HEX = "0123456789abcdef"
_B64URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

# 43 characters of base62, the shape of the bridge's own master token.
FAKE_ARENA_TOKEN = _shaped("", _HEX, 43)
# The OAuth access token shape an agent forwards in an Authorization header.
FAKE_OAUTH_TOKEN = _shaped("ya29.", _B64URL, 40)
# A GitHub personal access token, prefix assembled so the literal never
# appears in the source.
FAKE_GITHUB_PAT = _shaped("gh" + "p_", _B64URL, 32)
FAKE_CLI_TOKEN = _shaped("", _HEX, 32)
# Three dotted base64url segments: the JWT pattern, which is the most
# expensive one in the battery.
FAKE_JWT = ".".join((
    _shaped("eyJ", _B64URL, 34),
    _shaped("eyJ", _B64URL, 40),
    _shaped("", _B64URL, 43),
))

# A realistic audit record: mostly boring metadata, one embedded bearer
# token, one sensitive key, and a nested command line of the shape the
# bridge records when it proxies a request.
AUDIT_EVENT: dict[str, object] = {
    "ts": "2026-01-01T00:00:00+00:00",
    "event": "http_request",
    "method": "POST",
    "path": "/v1/mission/run",
    "status": 200,
    "duration_ms": 12.5,
    "peer": "10.0.0.7",
    "authorization": f"Bearer {FAKE_OAUTH_TOKEN}",
    "headers": {
        "user-agent": "arena-agent/4.170.0",
        "x-arena-token": FAKE_ARENA_TOKEN,
        "content-type": "application/json",
    },
    "body": {
        "mission_id": "m-4711",
        "steps": [
            f"curl -H 'Authorization: Bearer {FAKE_GITHUB_PAT}' https://api.example.com/v1/x",
            f"arena serve --token {FAKE_CLI_TOKEN}",
            "psql postgres://svc:" + "hunter2hunter2"
            + "@db.internal:5432/arena -c 'select 1'",
        ],
        "retries": 3,
        "dry_run": False,
    },
}

SHORT_VALUE = "200"
CLEAN_LONG_VALUE = (
    "GET /v1/skills/list?limit=50&offset=0 completed in 12ms for peer 10.0.0.7 "
    "with revision 8f14e45fceea167a5a36dedd4bea2543 on host arena-runner-03"
)
CREDENTIAL_VALUE = f"Authorization: Bearer {FAKE_JWT}"
KEY_NAMES = [
    "path", "method", "status", "duration_ms", "authorization",
    "x_arena_token", "user_agent", "mission_id", "private_key", "peer",
]


def test_redact_string_short_value(benchmark) -> None:
    """The fast path: below 16 chars no shape pattern can match."""
    assert benchmark(redact_string, SHORT_VALUE) == SHORT_VALUE


def test_redact_string_clean_long_value(benchmark) -> None:
    """The expensive common case: every pattern runs, none matches."""
    assert benchmark(redact_string, CLEAN_LONG_VALUE) == CLEAN_LONG_VALUE


def test_redact_string_with_credential(benchmark) -> None:
    """A real match, so the substitution cost is measured too."""
    assert "<redacted:" in benchmark(redact_string, CREDENTIAL_VALUE)


def test_redact_value_audit_event(benchmark) -> None:
    """The whole recursive walk over a representative audit record."""
    scrubbed = benchmark(redact_value, AUDIT_EVENT)
    assert scrubbed["authorization"] == "<redacted>"
    assert scrubbed["status"] == 200


def test_is_sensitive_key_batch(benchmark) -> None:
    """Key classification runs once per field of every redacted record."""

    def classify() -> int:
        return sum(1 for key in KEY_NAMES if is_sensitive_key(key))

    assert benchmark(classify) == 3


def test_redact_string_with_registered_literals(benchmark) -> None:
    """Literals are scanned before the fast path, on every call."""
    literals = [f"{index:04d}" + "abcdefghijklmnopqrstuvwxyz" for index in range(8)]
    for literal in literals:
        register_literal_secret(literal, "bridge-token")
    try:
        text = f"arena serve --token {literals[-1]} --port 8765 --host 127.0.0.1"
        assert "<redacted:" in benchmark(redact_string, text)
    finally:
        for literal in literals:
            unregister_literal_secret(literal)
