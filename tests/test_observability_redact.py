"""v4.45.0 tests for the shared observability.redact module.

These tests verify the module in isolation. Consumer-side
integration (audit_log + request_log routing) is covered by
the existing tests -- adding this suite locks in the contract
for future emit-sites that use the same module.
"""
from __future__ import annotations

import pytest

from arena.observability.redact import (
    SENSITIVE_KEY_SUBSTRINGS,
    is_sensitive_key,
    redact_string,
    redact_value,
)


# ---------------------------------------------------------------------------
# is_sensitive_key
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("key,expected", [
    ("token", True),
    ("access_token", True),
    ("MY_API_KEY", True),
    ("password", True),
    ("PASSPHRASE", True),
    ("privateKey", True),
    ("some_credential_v2", True),
    # Not sensitive
    ("status", False),
    ("path", False),
    ("count", False),
])
def test_is_sensitive_key_shapes(key, expected):
    assert is_sensitive_key(key) is expected


def test_sensitive_key_substrings_is_frozenset():
    """Regression: keep the constant immutable so callers can't
    accidentally shrink the blocklist by ``.remove()``."""
    assert isinstance(SENSITIVE_KEY_SUBSTRINGS, frozenset)


# ---------------------------------------------------------------------------
# redact_string -- fast-path
# ---------------------------------------------------------------------------
def test_short_string_passthrough():
    """Strings shorter than 16 chars can't carry a credential
    that matches any of our patterns -- fast-path skips regex."""
    for s in ("", "x", "short", "still-tiny"):
        assert redact_string(s) is s or redact_string(s) == s


def test_ordinary_long_string_passthrough():
    text = "This is a perfectly normal log message about 42 tests running for 3.2s."
    assert redact_string(text) == text


# ---------------------------------------------------------------------------
# redact_string -- credential shapes (built at import time to
# sidestep GitHub secret-scanning; see identical pattern in
# tests/test_audit_value_redaction.py)
# ---------------------------------------------------------------------------
_SUFFIX = "1234567890abcdefghijklmnopqrstuvwxyz"
_CRED_FIXTURES = [
    ("Authorization: Bearer q7pjxhIBSnYhOcSAY9a7VK8Jt1lj" + _SUFFIX, "bearer"),
    ("Authorization: Basic dXNlcjpwYXNzd29yZDEyMzQ=" + _SUFFIX, "basic"),
    ("aws_access_key_id = " + "AKIA" + "IOSFODNN7EXAMPLE", "aws-access-key"),
    ("token=" + "ghp" + "_" + _SUFFIX + "1234567890", "github"),
    ("api_key=" + "sk" + "-" + _SUFFIX + "01234567", "openai-style"),
    ("bot=" + "xoxb" + "-1234567890-" + _SUFFIX, "slack"),
    ("key=" + "AIza" + "SyABCDEFGHIJKLMNOPQRSTUVWXYZ0123456", "google-api"),
    ("jwt=" + "eyJ" + "hbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NX0."
     + "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c", "jwt"),
    ("db=" + "postgres" + "://admin:hunter2@db.example.com:5432/prod", "uri-creds"),
    ("key: -----BEGIN " + "RSA PRIVATE KEY" + "-----\nMIIC...", "ssh-key"),
]


@pytest.mark.parametrize("payload,label", _CRED_FIXTURES)
def test_redact_string_scrubs_credential(payload, label):
    out = redact_string(payload)
    assert f"<redacted:{label}>" in out


def test_redact_string_is_idempotent():
    """Calling twice should not change the output (no double-
    redaction, no over-eager pattern rematch on the placeholder)."""
    original = "Bearer q7pjxhIBSnYhOcSAY9a7VK8Jt1lj" + _SUFFIX
    once = redact_string(original)
    twice = redact_string(once)
    assert once == twice


def test_redact_string_multiple_secrets():
    text = (
        "GH_TOKEN=" + "ghp" + "_1234567890abcdefghijklmnopqrstuvwxyz\n"
        "AWS_KEY=" + "AKIA" + "IOSFODNN7EXAMPLE\n"
        "OPENAI=" + "sk" + "-abcdefghijklmnopqrstuvwxyz01234567"
    )
    out = redact_string(text)
    assert ("ghp" + "_1234567890") not in out
    assert ("AKIA" + "IOSFODNN7EXAMPLE") not in out
    assert ("sk" + "-abcdefghijklm") not in out


# ---------------------------------------------------------------------------
# redact_value recursion
# ---------------------------------------------------------------------------
def test_redact_value_leaves_primitives():
    for v in (42, True, False, None, 3.14):
        assert redact_value(v) == v


def test_redact_value_recurses_dict():
    v = {
        "outer": {"api_key": "leak", "inner": {"password": "hunter2"}},
        "safe": "hello",
    }
    out = redact_value(v)
    assert out["outer"]["api_key"] == "<redacted>"
    assert out["outer"]["inner"]["password"] == "<redacted>"
    assert out["safe"] == "hello"


def test_redact_value_recurses_list_and_tuple():
    v = [
        "curl -H 'Authorization: Bearer " + "ghp" + "_1234567890abcdefghijklmnop'",
        {"token": "leaked"},
        (1, "safe", {"password": "leak2"}),
    ]
    out = redact_value(v)
    assert "<redacted:" in out[0]
    assert out[1]["token"] == "<redacted>"
    assert out[2][0] == 1
    assert out[2][1] == "safe"
    assert out[2][2]["password"] == "<redacted>"


def test_redact_value_does_not_mutate_input():
    """Immutability contract: the sanitizer must not mutate its
    input because callers may use the same event for metrics /
    tracing."""
    original = {"token": "keep-me-original", "n": 1}
    _ = redact_value(original)
    # Original still has the raw value.
    assert original["token"] == "keep-me-original"


# ---------------------------------------------------------------------------
# Cross-module contract: audit.py's back-compat aliases point at
# the same objects.
# ---------------------------------------------------------------------------
def test_audit_module_aliases_are_the_same():
    """arena.observability.audit imported the helpers under
    underscored names for back-compat. They MUST be the same
    objects as the public entry points -- otherwise a future
    edit to the shared module would silently skip the audit
    log."""
    from arena.observability import audit
    assert audit._redact_value_patterns is redact_string
    assert audit._scrub is redact_value
    assert audit._is_sensitive_key is is_sensitive_key
    assert audit._SENSITIVE_KEY_SUBSTRINGS is SENSITIVE_KEY_SUBSTRINGS
