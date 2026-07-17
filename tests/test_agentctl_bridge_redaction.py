"""Tests for the v4.41.0 URL-redaction helper (audit finding
#4: fallback diagnostics leaked full Tailscale / ngrok
hostnames into anything that captured stderr).
"""
from __future__ import annotations

import io

import pytest

from arena.agentctl_cli import agentctl_bridge as ab


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("ARENA_AGENTCTL_LOG_FULL_URLS", raising=False)
    yield


class _FakeStderr(io.StringIO):
    """Non-TTY stderr stand-in -- ``isatty`` returns False, which
    is what triggers redaction. StringIO would default to
    False anyway; making it explicit for readability."""
    def isatty(self):
        return False


class _FakeTTY(io.StringIO):
    def isatty(self):
        return True


# ---------------------------------------------------------------------------
# TTY vs non-TTY behaviour
# ---------------------------------------------------------------------------
def test_tty_stderr_leaves_url_alone(monkeypatch):
    """Operator staring at their own terminal already knows their
    infrastructure; redaction there would just be annoying."""
    monkeypatch.setattr(ab.sys, "stderr", _FakeTTY())
    url = "https://cachyos-x8664.tail328f18.ts.net"
    assert ab._redact_url_for_log(url) == url


def test_non_tty_stderr_redacts_public_hostname(monkeypatch):
    monkeypatch.setattr(ab.sys, "stderr", _FakeStderr())
    url = "https://cachyos-x8664.tail328f18.ts.net"
    got = ab._redact_url_for_log(url)
    # scheme preserved
    assert got.startswith("https://")
    # tld preserved
    assert got.endswith(".net")
    # 8-char prefix preserved
    assert "cachyos-" in got
    # secret-ish middle stripped
    assert "tail328f18" not in got


def test_non_tty_stderr_redacts_ngrok_reserved_domain(monkeypatch):
    monkeypatch.setattr(ab.sys, "stderr", _FakeStderr())
    url = "https://pout-shingle-mystify.ngrok-free.dev"
    got = ab._redact_url_for_log(url)
    assert got.startswith("https://")
    assert got.endswith(".dev")
    assert "pout-shingle-mystify" not in got


def test_non_tty_stderr_redacts_cloudflared_rotation(monkeypatch):
    monkeypatch.setattr(ab.sys, "stderr", _FakeStderr())
    url = "https://hair-innovation-tourism-defence.trycloudflare.com"
    got = ab._redact_url_for_log(url)
    assert got.endswith(".com")
    assert "innovation-tourism" not in got


# ---------------------------------------------------------------------------
# Env override
# ---------------------------------------------------------------------------
def test_env_override_disables_redaction_even_on_non_tty(monkeypatch):
    monkeypatch.setattr(ab.sys, "stderr", _FakeStderr())
    monkeypatch.setenv("ARENA_AGENTCTL_LOG_FULL_URLS", "1")
    url = "https://pout-shingle-mystify.ngrok-free.dev"
    assert ab._redact_url_for_log(url) == url


# ---------------------------------------------------------------------------
# Non-sensitive hosts pass through unchanged
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("url", [
    "http://localhost:8765",
    "http://127.0.0.1:8765",
    "http://10.57.152.120:8765",       # ZeroTier LAN
    "http://192.168.1.10:8765",        # generic RFC1918
    "http://169.254.169.254/latest/",  # cloud IMDS -- would be blocked by
                                       # url_cache allowlist, but here we just
                                       # note that redaction leaves it alone
    "https://short.io",                # host shorter than 12 chars
])
def test_short_and_private_hosts_pass_through(monkeypatch, url):
    monkeypatch.setattr(ab.sys, "stderr", _FakeStderr())
    assert ab._redact_url_for_log(url) == url


# ---------------------------------------------------------------------------
# Broken input is redacted defensively
# ---------------------------------------------------------------------------
def test_malformed_url_returns_placeholder_or_original(monkeypatch):
    """We must never raise from a diagnostic helper. Empty and
    weird inputs go through without an exception."""
    monkeypatch.setattr(ab.sys, "stderr", _FakeStderr())
    # empty -> passes through (nothing to redact)
    assert ab._redact_url_for_log("") == ""
    # non-http-y garbage -> pass through
    assert isinstance(ab._redact_url_for_log("not-a-url"), str)


def test_stderr_isatty_exception_treated_as_non_tty(monkeypatch):
    """If stderr is a weird test double that raises on isatty,
    redact rather than crash."""
    class _Broken:
        def isatty(self):
            raise RuntimeError("mock")
    monkeypatch.setattr(ab.sys, "stderr", _Broken())
    url = "https://cachyos-x8664.tail328f18.ts.net"
    got = ab._redact_url_for_log(url)
    assert "tail328f18" not in got
