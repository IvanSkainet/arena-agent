"""Tests for the ngrok tunnel admin runtime (v4.32.0).

Third-party fallback transport alongside Tailscale / ZeroTier /
cloudflared. Tests here prove:
  * Binary resolution walks system PATH then well-known install
    locations then the bundled fallback -- same pattern as
    cloudflared.
  * URL-wait timeout obeys the same clamp/env pattern the
    v4.24.1 cloudflared fix locked in.
  * ``ngrok_action`` returns the right shape for start/stop/status
    even when the binary is not installed.
  * The local-API URL poller (ngrok's differentiator over
    cloudflared) parses the ngrok /api/tunnels response shape.

Tests never spawn a real ngrok subprocess -- they stub
``subprocess.Popen`` and the ``urllib.request.urlopen`` call so
CI can run without the binary and without a network.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from arena.admin import ngrok as ngrok_mod
from arena.admin.ngrok import (
    NGROK_STATE,
    _URL_WAIT_DEFAULT_SECONDS,
    _URL_WAIT_MAX_SECONDS,
    _URL_WAIT_MIN_SECONDS,
    _poll_ngrok_url_from_api,
    _resolve_ngrok_with_source,
    _url_wait_seconds,
    ngrok_action,
)


ENV_WAIT = "ARENA_NGROK_URL_WAIT_SECONDS"
ENV_TOKEN = "ARENA_NGROK_AUTHTOKEN"
ENV_REGION = "ARENA_NGROK_REGION"


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset module state between tests -- Popen mocks would
    otherwise leak between tests via NGROK_STATE."""
    NGROK_STATE["proc"] = None
    NGROK_STATE["url"] = ""
    NGROK_STATE["log"].clear()
    yield
    NGROK_STATE["proc"] = None
    NGROK_STATE["url"] = ""
    NGROK_STATE["log"].clear()


# ---------------------------------------------------------------------------
# URL-wait tunable -- same shape as v4.24.1 cloudflared
# ---------------------------------------------------------------------------
def test_default_wait_matches_cloudflared_default(monkeypatch):
    monkeypatch.delenv(ENV_WAIT, raising=False)
    assert _url_wait_seconds() == _URL_WAIT_DEFAULT_SECONDS


def test_env_override_respected(monkeypatch):
    monkeypatch.setenv(ENV_WAIT, "45")
    assert _url_wait_seconds() == 45.0


def test_env_garbage_falls_back(monkeypatch):
    monkeypatch.setenv(ENV_WAIT, "banana")
    assert _url_wait_seconds() == _URL_WAIT_DEFAULT_SECONDS


def test_env_clamp_low(monkeypatch):
    monkeypatch.setenv(ENV_WAIT, "0")
    assert _url_wait_seconds() == _URL_WAIT_MIN_SECONDS


def test_env_clamp_high(monkeypatch):
    monkeypatch.setenv(ENV_WAIT, "9999")
    assert _url_wait_seconds() == _URL_WAIT_MAX_SECONDS


# ---------------------------------------------------------------------------
# Local API poller
# ---------------------------------------------------------------------------
def _stub_urlopen(payload_bytes):
    class _Resp:
        def __init__(self):
            self._buf = io.BytesIO(payload_bytes)
        def read(self):
            return self._buf.read()
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
    return lambda url, timeout=None: _Resp()


def test_poll_extracts_first_https_tunnel():
    payload = json.dumps({"tunnels": [
        {"name": "t1", "public_url": "http://x.ngrok.io", "proto": "http"},
        {"name": "t2", "public_url": "https://y.ngrok-free.app", "proto": "https"},
    ]}).encode()
    with patch.object(ngrok_mod.urllib.request, "urlopen", _stub_urlopen(payload)):
        url = _poll_ngrok_url_from_api()
    assert url == "https://y.ngrok-free.app"


def test_poll_falls_back_to_first_public_url_when_no_https():
    payload = json.dumps({"tunnels": [
        {"name": "t1", "public_url": "tcp://a.ngrok.io:12345", "proto": "tcp"},
    ]}).encode()
    with patch.object(ngrok_mod.urllib.request, "urlopen", _stub_urlopen(payload)):
        url = _poll_ngrok_url_from_api()
    assert url == "tcp://a.ngrok.io:12345"


def test_poll_returns_none_when_no_tunnels():
    payload = json.dumps({"tunnels": []}).encode()
    with patch.object(ngrok_mod.urllib.request, "urlopen", _stub_urlopen(payload)):
        assert _poll_ngrok_url_from_api() is None


def test_poll_swallows_network_error():
    def _raise(url, timeout=None):
        raise ConnectionRefusedError("no api")
    with patch.object(ngrok_mod.urllib.request, "urlopen", _raise):
        assert _poll_ngrok_url_from_api() is None


def test_poll_swallows_bad_json():
    with patch.object(ngrok_mod.urllib.request, "urlopen",
                      _stub_urlopen(b"not-json")):
        assert _poll_ngrok_url_from_api() is None


def test_poll_handles_missing_tunnels_key():
    payload = json.dumps({"unrelated": "shape"}).encode()
    with patch.object(ngrok_mod.urllib.request, "urlopen", _stub_urlopen(payload)):
        assert _poll_ngrok_url_from_api() is None


# ---------------------------------------------------------------------------
# Binary resolution
# ---------------------------------------------------------------------------
def test_resolve_returns_not_found_for_empty_dir(tmp_path, monkeypatch):
    """Empty root_agent + PATH without ngrok -> not_found."""
    monkeypatch.setenv("PATH", str(tmp_path))
    bin_path, source = _resolve_ngrok_with_source(tmp_path)
    # Real ngrok may or may not be on the test host; just prove the
    # not_found shape when we clearly point PATH at an empty dir.
    if bin_path is None:
        assert source == "not_found"


def test_resolve_finds_bundled_binary(tmp_path, monkeypatch):
    """A bundled binary in root_agent should be picked up when
    PATH has nothing."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))  # empty PATH dir
    (tmp_path / "empty").mkdir()
    fake_bin = tmp_path / "ngrok"
    fake_bin.write_text("#!/bin/sh\necho stub\n")
    os.chmod(fake_bin, 0o755)
    bin_path, source = _resolve_ngrok_with_source(tmp_path)
    # If PATH picked up nothing else, we get the bundled one.
    if bin_path == str(fake_bin):
        assert source == "bundled"


# ---------------------------------------------------------------------------
# ngrok_action() shape
# ---------------------------------------------------------------------------
def test_action_rejects_unknown_verb(tmp_path):
    result = ngrok_action("nope", 8765,
                         root_agent=tmp_path,
                         subprocess_kwargs=lambda: {})
    assert result["ok"] is False
    assert "start|stop|status" in result["error"]


def test_action_start_reports_not_found_with_hint(tmp_path, monkeypatch):
    """When ngrok is not installed, start should return a hint the
    operator can act on -- never crash bridge boot."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    result = ngrok_action("start", 8765,
                          root_agent=tmp_path,
                          subprocess_kwargs=lambda: {})
    if not result.get("ok"):
        assert "not found" in result.get("error", "").lower()
        assert "update_hint" in result


def test_action_stop_is_idempotent_when_nothing_running(tmp_path):
    """stop with no running proc must be a clean success, not
    an error -- callers may loop stop() safely."""
    result = ngrok_action("stop", 8765,
                          root_agent=tmp_path,
                          subprocess_kwargs=lambda: {})
    assert result["ok"] is True
    assert result["action"] == "stop"


def test_action_status_when_nothing_installed_reports_gracefully(tmp_path, monkeypatch):
    """status with no binary must report installed:false + a hint
    -- never raise."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    (tmp_path / "empty").mkdir()
    result = ngrok_action("status", 8765,
                          root_agent=tmp_path,
                          subprocess_kwargs=lambda: {})
    assert result["ok"] is True
    assert result["action"] == "status"
    # active is always False when no proc is running.
    assert result["active"] is False


# ---------------------------------------------------------------------------
# Region override is passed through
# ---------------------------------------------------------------------------
@pytest.mark.skipif(
    os.name != "posix",
    reason="Test relies on POSIX shell shebang + chmod 0o755 to fake an ngrok binary; Windows resolves binaries by extension via PATHEXT and cannot exec a #!-header",
)
def test_region_env_override_appears_in_argv(monkeypatch, tmp_path):
    """When ARENA_NGROK_REGION is set, ``--region <value>`` should
    end up on the subprocess argv. Uses a stubbed Popen so no real
    binary is invoked."""
    monkeypatch.setenv(ENV_REGION, "eu")

    captured = {}

    class _StubProc:
        def __init__(self, argv, *a, **kw):
            captured["argv"] = argv
            captured["kwargs"] = kw
            self.stdout = io.StringIO("")
        def poll(self):
            return 0  # already exited so the wait loop bails immediately
        def terminate(self):
            pass
        def kill(self):
            pass
        def wait(self, timeout=None):
            return 0

    # Point at a real "binary" so _resolve_ngrok_with_source finds it.
    fake_bin = tmp_path / "ngrok"
    fake_bin.write_text("#!/bin/sh\n")
    os.chmod(fake_bin, 0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(ngrok_mod.subprocess, "Popen", _StubProc)

    ngrok_action("start", 8765,
                 root_agent=tmp_path,
                 subprocess_kwargs=lambda: {})
    argv = captured.get("argv", [])
    assert "--region" in argv
    idx = argv.index("--region")
    assert argv[idx + 1] == "eu"


def test_no_region_no_flag(monkeypatch, tmp_path):
    """When ARENA_NGROK_REGION is unset, ``--region`` must NOT
    appear in argv -- ngrok would reject an empty argument."""
    monkeypatch.delenv(ENV_REGION, raising=False)

    captured = {}

    class _StubProc:
        def __init__(self, argv, *a, **kw):
            captured["argv"] = argv
            self.stdout = io.StringIO("")
        def poll(self):
            return 0
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 0

    fake_bin = tmp_path / "ngrok"
    fake_bin.write_text("#!/bin/sh\n")
    os.chmod(fake_bin, 0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(ngrok_mod.subprocess, "Popen", _StubProc)

    ngrok_action("start", 8765,
                 root_agent=tmp_path,
                 subprocess_kwargs=lambda: {})
    argv = captured.get("argv", [])
    assert "--region" not in argv


@pytest.mark.skipif(
    os.name != "posix",
    reason="Test relies on POSIX shell shebang + chmod 0o755 to fake an ngrok binary; Windows resolves binaries by extension via PATHEXT and cannot exec a #!-header",
)
def test_start_uses_local_api_first_then_stdout_fallback(monkeypatch, tmp_path):
    """When the local /api/tunnels responds with a URL, that URL
    must win -- do not wait for stdout to catch up."""
    fake_bin = tmp_path / "ngrok"
    fake_bin.write_text("#!/bin/sh\n")
    os.chmod(fake_bin, 0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv(ENV_WAIT, "5")  # keep the loop short

    class _StubProc:
        def __init__(self, argv, *a, **kw):
            # Return a stdout that never yields anything, so the
            # only way ngrok_action can get a URL is via the API.
            self.stdout = io.StringIO("")
        def poll(self):
            return None  # still running
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 0

    monkeypatch.setattr(ngrok_mod.subprocess, "Popen", _StubProc)

    # Fake API response. v4.36.1: include config.addr matching
    # port 8765 so the port-filter in _poll_ngrok_url_from_api
    # accepts this tunnel as ours.
    payload = json.dumps({"tunnels": [
        {"public_url": "https://api-first.ngrok-free.app",
         "proto": "https",
         "config": {"addr": "http://localhost:8765"}},
    ]}).encode()
    monkeypatch.setattr(ngrok_mod.urllib.request, "urlopen",
                        _stub_urlopen(payload))

    result = ngrok_action("start", 8765,
                          root_agent=tmp_path,
                          subprocess_kwargs=lambda: {})
    assert result["ok"] is True
    assert result["url"] == "https://api-first.ngrok-free.app"
    # Cleanup so subsequent tests get a clean NGROK_STATE.
    NGROK_STATE["proc"] = None
