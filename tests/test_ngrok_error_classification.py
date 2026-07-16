"""Tests for the v4.36.0 ngrok error classifier + fail-fast.

Two behaviours to prove:

1. ``_classify_error`` maps the six most common ngrok stdout /
   stderr patterns into short structured error codes with an
   actionable hint. Missing pattern -> ``("unknown", ...)``.

2. ``_start_ngrok`` no longer waits the full URL-wait timeout
   when the child process dies early -- it returns immediately
   with ``process_died_early: True`` and the classified error
   code. This is the v4.36.0 fix for the v4.33.1 live-smoke
   finding "ngrok timed out after 30s" when the truth was
   "died at 1.5s because no authtoken".
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from arena.admin import ngrok as ngrok_mod
from arena.admin.ngrok import NGROK_STATE, _classify_error, _start_ngrok


@pytest.fixture(autouse=True)
def _reset_state():
    NGROK_STATE["proc"] = None
    NGROK_STATE["url"] = ""
    NGROK_STATE["log"].clear()
    yield
    NGROK_STATE["proc"] = None
    NGROK_STATE["url"] = ""
    NGROK_STATE["log"].clear()


@pytest.fixture(autouse=True)
def _no_real_ngrok_api(monkeypatch):
    """Neuter the local-API poller and authtoken-applier so tests
    can't accidentally hit a real ngrok instance living on the
    test host. Discovered on the v4.36.0 push: bridge had a
    reserved-domain ngrok running from an unrelated shell, and
    the poller returned its URL instead of the expected timeout,
    flipping test assertions."""
    monkeypatch.setattr(ngrok_mod, "_poll_ngrok_url_from_api",
                        lambda **kw: None)
    monkeypatch.setattr(ngrok_mod, "_apply_authtoken",
                        lambda bin_path, subprocess_kwargs: None)


# ---------------------------------------------------------------------------
# Pattern matcher
# ---------------------------------------------------------------------------
def test_classify_needs_authtoken_from_err_code():
    log = ['t=... lvl=eror msg="ERR_NGROK_4018 ..."']
    code, hint = _classify_error(log)
    assert code == "needs_authtoken"
    assert "authtoken" in hint.lower()
    assert "dashboard.ngrok.com" in hint


def test_classify_needs_authtoken_from_english_text():
    log = ["ERROR: This ngrok session is not authenticated. Sign up ..."]
    code, hint = _classify_error(log)
    assert code == "needs_authtoken"


def test_classify_session_limit_hit():
    log = ["ERR_NGROK_108: only 1 simultaneous ngrok agent session"]
    code, hint = _classify_error(log)
    assert code == "session_limit_hit"
    assert "one active session" in hint or "simultaneous" in hint.lower() or "one" in hint.lower()


def test_classify_invalid_authtoken():
    log = ["ERR_NGROK_3200: invalid authtoken value"]
    code, _ = _classify_error(log)
    assert code == "invalid_authtoken"


def test_classify_invalid_region():
    log = ["ERR_NGROK_121: region xx is not a valid region"]
    code, _ = _classify_error(log)
    assert code == "invalid_region"


def test_classify_tunnel_limit_hit():
    log = ["ERR_NGROK_3204: too many tunnels for this plan"]
    code, _ = _classify_error(log)
    assert code == "tunnel_limit_hit"


def test_classify_api_port_in_use():
    log = ["listen tcp 127.0.0.1:4040: bind: address already in use"]
    code, hint = _classify_error(log)
    assert code == "api_port_in_use"
    assert "pkill" in hint or "4040" in hint


def test_classify_returns_unknown_for_unmatched():
    log = ["some completely unrelated log line"]
    code, hint = _classify_error(log)
    assert code == "unknown"
    assert "ngrok" in hint.lower() or "docs" in hint.lower()


def test_classify_empty_log_returns_unknown():
    code, hint = _classify_error([])
    assert code == "unknown"


# ---------------------------------------------------------------------------
# Fail-fast on early process death
# ---------------------------------------------------------------------------
def test_start_ngrok_returns_fast_when_process_dies_early(monkeypatch, tmp_path):
    """The v4.36.0 fix: when the child exits before opening a
    tunnel, we return immediately with process_died_early=True
    instead of waiting the full URL-wait timeout."""

    # Force a very long URL-wait so the test would obviously
    # stall if the fail-fast path were broken.
    monkeypatch.setenv("ARENA_NGROK_URL_WAIT_SECONDS", "60")

    class _DyingProc:
        """Stub that reports as running for the first poll then
        exited on every subsequent call -- mimics the auth-fail
        pattern from the v4.33.1 live-smoke."""
        _poll_count = 0

        def __init__(self, *a, **kw):
            self.stdout = io.StringIO(
                "t=2026 lvl=eror msg=ERR_NGROK_4018 not authenticated\n"
                "ERROR: session is not authenticated\n"
            )
            self.__class__._poll_count = 0

        def poll(self):
            self.__class__._poll_count += 1
            if self.__class__._poll_count <= 1:
                return None
            return 1  # exited

        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 1

    monkeypatch.setattr(ngrok_mod.subprocess, "Popen",
                        lambda *a, **kw: _DyingProc())

    import time
    t0 = time.monotonic()
    result = _start_ngrok("/usr/bin/ngrok", 8765,
                          subprocess_kwargs=lambda: {})
    elapsed = time.monotonic() - t0

    # Fail-fast: must complete in well under the 60s wait.
    assert elapsed < 5.0, f"start took {elapsed:.1f}s -- expected < 5s"
    assert result["ok"] is False
    assert result.get("process_died_early") is True
    assert result.get("error_code") == "needs_authtoken"
    assert "authtoken" in (result.get("hint") or "").lower()
    # Log field should carry ngrok's raw lines so operators can
    # still inspect the full context if the classifier picked wrong.
    assert any("ERR_NGROK_4018" in line for line in result.get("log") or [])


def test_start_ngrok_hint_makes_authtoken_setup_obvious(monkeypatch, tmp_path):
    """The hint must include the exact URL + env-var name so an
    operator can copy-paste the fix without a docs search."""
    monkeypatch.setenv("ARENA_NGROK_URL_WAIT_SECONDS", "5")

    class _DyingProc:
        _poll_count = 0
        def __init__(self, *a, **kw):
            self.stdout = io.StringIO(
                "ERROR: This ngrok session is not authenticated.\n"
                "ERROR: ERR_NGROK_4018\n"
            )
            self.__class__._poll_count = 0
        def poll(self):
            self.__class__._poll_count += 1
            return None if self.__class__._poll_count <= 1 else 1
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 1

    monkeypatch.setattr(ngrok_mod.subprocess, "Popen",
                        lambda *a, **kw: _DyingProc())

    result = _start_ngrok("/usr/bin/ngrok", 8765,
                          subprocess_kwargs=lambda: {})
    hint = result.get("hint", "")
    assert "ARENA_NGROK_AUTHTOKEN" in hint
    assert "dashboard.ngrok.com" in hint
    assert "add-authtoken" in hint  # tells operator the exact CLI


def test_start_ngrok_error_message_names_the_code(monkeypatch, tmp_path):
    """The top-level ``error`` string must include the classified
    code so a legacy caller that only reads ``error`` still sees
    the actionable classification."""
    monkeypatch.setenv("ARENA_NGROK_URL_WAIT_SECONDS", "5")

    class _DyingProc:
        _c = 0
        def __init__(self, *a, **kw):
            self.stdout = io.StringIO("ERR_NGROK_4018 not authenticated\n")
            self.__class__._c = 0
        def poll(self):
            self.__class__._c += 1
            return None if self.__class__._c <= 1 else 1
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 1

    monkeypatch.setattr(ngrok_mod.subprocess, "Popen",
                        lambda *a, **kw: _DyingProc())

    result = _start_ngrok("/usr/bin/ngrok", 8765,
                          subprocess_kwargs=lambda: {})
    assert "needs_authtoken" in result["error"]


def test_start_ngrok_timeout_path_still_works(monkeypatch, tmp_path):
    """When the process stays alive but never opens a tunnel
    (rare -- silent stall), we still hit the timeout path and
    return an unknown-classifier response."""
    monkeypatch.setenv("ARENA_NGROK_URL_WAIT_SECONDS", "1")

    class _SilentProc:
        def __init__(self, *a, **kw):
            self.stdout = io.StringIO("")
        def poll(self): return None  # always alive
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 0

    monkeypatch.setattr(ngrok_mod.subprocess, "Popen",
                        lambda *a, **kw: _SilentProc())

    # Neuter the API poller so the test doesn't try to hit
    # 127.0.0.1:4040 on the CI runner.
    monkeypatch.setattr(ngrok_mod, "_poll_ngrok_url_from_api",
                        lambda **kw: None)

    result = _start_ngrok("/usr/bin/ngrok", 8765,
                          subprocess_kwargs=lambda: {})
    assert result["ok"] is False
    assert result.get("process_died_early") is False
    assert result.get("error_code") == "unknown"
    assert "timed out" in result["error"]
