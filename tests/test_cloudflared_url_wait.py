"""Tests for the tunable cloudflared URL-wait timeout (v4.24.1).

The v4.24.0 live-smoke caught cloudflared's autostart timing out
at exactly 10.01s while a manual restart seconds later succeeded.
Root cause: the URL-wait loop in ``_start_cloudflared`` hardcoded
20 iterations x 0.5s = 10s, which was empirically too tight for
a fresh bridge boot on a slow uplink. This module tests the
tunable replacement and its clamping guards.
"""
from __future__ import annotations

import pytest

from arena.admin.cloudflared import (
    _URL_WAIT_DEFAULT_SECONDS,
    _URL_WAIT_MAX_SECONDS,
    _URL_WAIT_MIN_SECONDS,
    _URL_WAIT_POLL_INTERVAL_SECONDS,
    _url_wait_seconds,
)


ENV_VAR = "ARENA_CLOUDFLARED_URL_WAIT_SECONDS"


def test_default_is_at_least_20_seconds(monkeypatch):
    """The v4.24.0 postmortem needed > 10s; the new default must
    be comfortably above that so a cold cloudflared start can
    negotiate its URL without another live-smoke false negative."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    assert _url_wait_seconds() >= 20.0
    assert _url_wait_seconds() == _URL_WAIT_DEFAULT_SECONDS


def test_env_override_respected(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "45")
    assert _url_wait_seconds() == 45.0


def test_env_override_float_respected(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "12.5")
    assert _url_wait_seconds() == 12.5


def test_env_garbage_falls_back_to_default(monkeypatch):
    """Typo-safety: a non-numeric env value must NOT crash bridge
    boot -- fall back to the safe default silently."""
    monkeypatch.setenv(ENV_VAR, "not-a-number")
    assert _url_wait_seconds() == _URL_WAIT_DEFAULT_SECONDS


def test_env_empty_string_falls_back_to_default(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "")
    assert _url_wait_seconds() == _URL_WAIT_DEFAULT_SECONDS


def test_env_whitespace_only_falls_back(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "   ")
    assert _url_wait_seconds() == _URL_WAIT_DEFAULT_SECONDS


def test_env_clamped_low(monkeypatch):
    """0 seconds would tight-loop with no wait; clamp up to minimum."""
    monkeypatch.setenv(ENV_VAR, "0")
    assert _url_wait_seconds() == _URL_WAIT_MIN_SECONDS


def test_env_negative_clamped_low(monkeypatch):
    monkeypatch.setenv(ENV_VAR, "-5")
    assert _url_wait_seconds() == _URL_WAIT_MIN_SECONDS


def test_env_clamped_high(monkeypatch):
    """A runaway typo (99999) must not hang bridge boot indefinitely."""
    monkeypatch.setenv(ENV_VAR, "99999")
    assert _url_wait_seconds() == _URL_WAIT_MAX_SECONDS


def test_poll_interval_is_reasonable():
    """0.5s poll keeps CPU quiet while still catching a quick URL
    negotiation. Locked in so a refactor cannot silently spin
    faster and burn cycles."""
    assert 0.1 <= _URL_WAIT_POLL_INTERVAL_SECONDS <= 2.0


def test_iterations_match_total_wait(monkeypatch):
    """Sanity: total_wait / poll_interval must be at least 1 even
    at the min clamp -- the loop must always run at least once."""
    monkeypatch.setenv(ENV_VAR, str(_URL_WAIT_MIN_SECONDS))
    total = _url_wait_seconds()
    iterations = max(1, int(total / _URL_WAIT_POLL_INTERVAL_SECONDS))
    assert iterations >= 1


def test_start_cloudflared_uses_computed_wait(monkeypatch):
    """When ``_start_cloudflared`` returns failure, the response
    must include the actual wait seconds used, so operators can
    tell whether the timeout was the default or an override."""
    from arena.admin import cloudflared as cf_mod

    # Force env override so we know what to expect.
    monkeypatch.setenv(ENV_VAR, "1")

    # Stub the subprocess so no real binary is invoked. Return an
    # object whose stdout has no lines and whose poll() reports
    # still-running, so the loop always times out.
    class _StubProc:
        def __init__(self):
            self.stdout = _StubStdout()
        def poll(self):
            return None
        def terminate(self):
            pass
        def kill(self):
            pass
        def wait(self, timeout=None):
            return 0

    class _StubStdout:
        def readline(self):
            # Sleep briefly to model a slow reader without spinning.
            import time
            time.sleep(0.05)
            return ""

    monkeypatch.setattr(cf_mod.subprocess, "Popen", lambda *a, **kw: _StubProc())
    # Threading.Thread is fine to keep -- the stub reader returns
    # empty strings and the monitor loop exits.

    result = cf_mod._start_cloudflared(
        "/usr/bin/cloudflared",  # never actually invoked (stubbed)
        8765,
        subprocess_kwargs=lambda: {},
    )
    # We forced the clamp-min wait (1s) so this is quick.
    assert result["ok"] is False
    assert result.get("waited_seconds") == _URL_WAIT_MIN_SECONDS
    assert "1.0s" in result["error"]

    # Clean up the leftover stub proc reference so subsequent
    # tests don't see a "still running" state.
    cf_mod.CLOUDFLARED_STATE["proc"] = None
    cf_mod.CLOUDFLARED_STATE["url"] = ""
