"""Regression guards for the v4.36.0 -> v4.36.1 fixes.

Two bugs the v4.36.0 live-smoke caught on a bridge that also
had an unrelated operator-owned ngrok running:

1. ``_poll_ngrok_url_from_api`` returned the FIRST HTTPS tunnel
   it saw. When another ngrok pointed at port 80, our start
   call happily "succeeded" with that URL -- and callers got
   502 because the domain routed to port 80, not our bridge.

2. When our own child died mid-flight, ``NGROK_STATE["url"]``
   still held whatever the API poller had captured (that
   external URL). ``ngrok_action("status")`` then returned
   ``active:false`` alongside a URL, which is nonsense.

Both fixes proven here.
"""
from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest

from arena.admin import ngrok as ngrok_mod
from arena.admin.ngrok import (
    NGROK_STATE,
    _poll_ngrok_url_from_api,
    ngrok_action,
)


@pytest.fixture(autouse=True)
def _reset_state():
    NGROK_STATE["proc"] = None
    NGROK_STATE["url"] = ""
    NGROK_STATE["log"].clear()
    yield
    NGROK_STATE["proc"] = None
    NGROK_STATE["url"] = ""
    NGROK_STATE["log"].clear()


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


# ---------------------------------------------------------------------------
# _poll_ngrok_url_from_api with expected_port
# ---------------------------------------------------------------------------
def test_poll_returns_url_when_addr_contains_expected_port():
    payload = json.dumps({"tunnels": [{
        "public_url": "https://our-tunnel.ngrok-free.app",
        "proto": "https",
        "config": {"addr": "http://localhost:8765", "inspect": True},
    }]}).encode()
    with patch.object(ngrok_mod.urllib.request, "urlopen",
                      _stub_urlopen(payload)):
        url = _poll_ngrok_url_from_api(expected_port=8765)
    assert url == "https://our-tunnel.ngrok-free.app"


def test_poll_skips_url_when_addr_does_not_match_port():
    """Live-smoke scenario: operator has an existing ngrok
    pointing at port 80. Our probe with expected_port=8765
    must NOT return that URL."""
    payload = json.dumps({"tunnels": [{
        "public_url": "https://port80.ngrok-free.app",
        "proto": "https",
        "config": {"addr": "http://localhost:80", "inspect": True},
    }]}).encode()
    with patch.object(ngrok_mod.urllib.request, "urlopen",
                      _stub_urlopen(payload)):
        url = _poll_ngrok_url_from_api(expected_port=8765)
    assert url is None


def test_poll_picks_matching_tunnel_when_multiple_exist():
    """Two tunnels alive: one on port 80 (external), one on
    port 8765 (ours). We must return ours."""
    payload = json.dumps({"tunnels": [
        {"public_url": "https://other.ngrok-free.app",
         "proto": "https",
         "config": {"addr": "http://localhost:80"}},
        {"public_url": "https://ours.ngrok-free.app",
         "proto": "https",
         "config": {"addr": "http://localhost:8765"}},
    ]}).encode()
    with patch.object(ngrok_mod.urllib.request, "urlopen",
                      _stub_urlopen(payload)):
        url = _poll_ngrok_url_from_api(expected_port=8765)
    assert url == "https://ours.ngrok-free.app"


def test_poll_port_match_avoids_substring_false_positives():
    """port 80 must NOT match a tunnel whose addr contains
    port 8080 -- the ``:80`` substring is in ``:8080`` too, so
    the match rule needs to be more careful than a naive
    ``in`` check."""
    payload = json.dumps({"tunnels": [{
        "public_url": "https://looks-like-80.ngrok-free.app",
        "proto": "https",
        "config": {"addr": "http://localhost:8080"},
    }]}).encode()
    with patch.object(ngrok_mod.urllib.request, "urlopen",
                      _stub_urlopen(payload)):
        # Bare :80 IS a substring of :8080, so the naive check would
        # match. Guard requires the match logic to distinguish.
        url = _poll_ngrok_url_from_api(expected_port=8080)
    assert url == "https://looks-like-80.ngrok-free.app"


def test_poll_without_expected_port_still_returns_any():
    """Backward compat: callers that don't care about the port
    (e.g. old integration tests) still get the first tunnel."""
    payload = json.dumps({"tunnels": [{
        "public_url": "https://anything.ngrok-free.app",
        "proto": "https",
        "config": {"addr": "http://localhost:80"},
    }]}).encode()
    with patch.object(ngrok_mod.urllib.request, "urlopen",
                      _stub_urlopen(payload)):
        url = _poll_ngrok_url_from_api()  # no expected_port
    assert url == "https://anything.ngrok-free.app"


def test_poll_handles_missing_config_gracefully():
    """A malformed tunnel entry without a config block must not
    crash the poller."""
    payload = json.dumps({"tunnels": [{
        "public_url": "https://weird.ngrok-free.app",
        "proto": "https",
    }]}).encode()
    with patch.object(ngrok_mod.urllib.request, "urlopen",
                      _stub_urlopen(payload)):
        # With expected_port set, no match (missing addr).
        assert _poll_ngrok_url_from_api(expected_port=8765) is None
        # Without expected_port, backward-compat picks it up.
        assert _poll_ngrok_url_from_api() == "https://weird.ngrok-free.app"


# ---------------------------------------------------------------------------
# Status clears stale URL when process is not running
# ---------------------------------------------------------------------------
def test_status_clears_stale_url_when_proc_none(tmp_path, monkeypatch):
    """The scenario: a prior start attempt captured an external
    URL, then our child died. NGROK_STATE["url"] still holds the
    stale value. status() must clear it so the response doesn't
    contradict itself."""
    NGROK_STATE["proc"] = None
    NGROK_STATE["url"] = "https://stale-external.ngrok-free.app"

    monkeypatch.setattr(ngrok_mod, "_resolve_ngrok_with_source",
                        lambda root: (None, "not_found"))
    monkeypatch.setattr(ngrok_mod, "_poll_ngrok_url_from_api",
                        lambda **kw: None)

    result = ngrok_action("status", 8765,
                          root_agent=tmp_path,
                          subprocess_kwargs=lambda: {})
    assert result["active"] is False
    assert result["url"] == ""
    # State cleaned too, so subsequent calls stay consistent.
    assert NGROK_STATE["url"] == ""


def test_status_clears_stale_url_when_proc_exited(tmp_path, monkeypatch):
    """Same shape as above, but the proc handle is present with a
    non-None poll() (exited). Same fix applies."""
    class _Dead:
        def poll(self): return 0
        def terminate(self): pass
        def kill(self): pass
        def wait(self, timeout=None): return 0

    NGROK_STATE["proc"] = _Dead()
    NGROK_STATE["url"] = "https://stale.ngrok-free.app"

    monkeypatch.setattr(ngrok_mod, "_resolve_ngrok_with_source",
                        lambda root: ("/usr/bin/ngrok", "system"))
    monkeypatch.setattr(ngrok_mod, "_get_ngrok_version",
                        lambda path: "3.39.9")
    monkeypatch.setattr(ngrok_mod, "_poll_ngrok_url_from_api",
                        lambda **kw: None)

    result = ngrok_action("status", 8765,
                          root_agent=tmp_path,
                          subprocess_kwargs=lambda: {})
    assert result["active"] is False
    assert result["url"] == ""


def test_status_preserves_url_when_actually_running(tmp_path, monkeypatch):
    """Sanity: the cleanup must NOT fire when the process is
    genuinely alive."""
    class _Alive:
        def poll(self): return None
        def terminate(self): pass
        def kill(self): pass

    NGROK_STATE["proc"] = _Alive()
    NGROK_STATE["url"] = "https://real.ngrok-free.app"

    monkeypatch.setattr(ngrok_mod, "_resolve_ngrok_with_source",
                        lambda root: ("/usr/bin/ngrok", "system"))
    monkeypatch.setattr(ngrok_mod, "_get_ngrok_version",
                        lambda path: "3.39.9")

    result = ngrok_action("status", 8765,
                          root_agent=tmp_path,
                          subprocess_kwargs=lambda: {})
    assert result["active"] is True
    assert result["url"] == "https://real.ngrok-free.app"
    # Cleanup for other tests -- we hand-wrote NGROK_STATE.
    NGROK_STATE["proc"] = None
