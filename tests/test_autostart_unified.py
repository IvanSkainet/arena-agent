"""Tests for the unified autostart module (v4.38.0).

Generalises the v4.22.1 cloudflared marker pattern to all
transports with a start/stop verb (tailscale + cloudflared +
ngrok). ZeroTier absent by design.

Guards:
  * TRANSPORTS registered correctly (ZT NOT in the list)
  * marker path + env var derive from transport name
  * is_enabled = env OR marker (OR-shape locked in)
  * enable writes atomically, disable is idempotent
  * state_snapshot has the shape /v1/autostart consumers expect
  * env-override case surfaces `env_override: true`

Also proves the v4.22.1 back-compat wrapper
(``cloudflared_autostart.py``) still delegates to the unified
module — the entire v4.22.1 test suite is untouched by this
release, so if the wrapper regressed that test would fail.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from arena.admin import autostart


ENV_TS = "ARENA_TAILSCALE_AUTOSTART"
ENV_CF = "ARENA_CLOUDFLARED_AUTOSTART"
ENV_NG = "ARENA_NGROK_AUTOSTART"


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
def test_registered_transports_exclude_zerotier():
    """ZeroTier deliberately absent -- membership is long-lived
    across restarts, no per-bridge start/stop verb."""
    assert set(autostart.TRANSPORTS) == {"tailscale", "cloudflared", "ngrok"}


def test_unknown_transport_raises_on_marker_path():
    with pytest.raises(ValueError):
        autostart.marker_path("bogus", "/tmp/x")


# ---------------------------------------------------------------------------
# Marker filename + env var derivation
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("transport,expected", [
    ("tailscale",   ".tailscale_autostart"),
    ("cloudflared", ".cloudflared_autostart"),
    ("ngrok",       ".ngrok_autostart"),
])
def test_marker_filename_convention(tmp_path, transport, expected):
    p = autostart.marker_path(transport, tmp_path)
    assert p.name == expected
    assert p.parent == tmp_path


@pytest.mark.parametrize("transport,expected", [
    ("tailscale",   "ARENA_TAILSCALE_AUTOSTART"),
    ("cloudflared", "ARENA_CLOUDFLARED_AUTOSTART"),
    ("ngrok",       "ARENA_NGROK_AUTOSTART"),
])
def test_env_var_name_convention(monkeypatch, transport, expected):
    monkeypatch.setenv(expected, "1")
    assert autostart.is_env_enabled(transport) is True
    monkeypatch.delenv(expected, raising=False)
    assert autostart.is_env_enabled(transport) is False


# ---------------------------------------------------------------------------
# is_enabled -- OR of env + marker
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("transport", autostart.TRANSPORTS)
def test_neither_signal_disabled(tmp_path, monkeypatch, transport):
    monkeypatch.delenv(f"ARENA_{transport.upper()}_AUTOSTART", raising=False)
    assert autostart.is_enabled(transport, tmp_path) is False


@pytest.mark.parametrize("transport", autostart.TRANSPORTS)
def test_marker_alone_enabled(tmp_path, monkeypatch, transport):
    monkeypatch.delenv(f"ARENA_{transport.upper()}_AUTOSTART", raising=False)
    autostart.enable(transport, tmp_path, port=8765)
    assert autostart.is_enabled(transport, tmp_path) is True


@pytest.mark.parametrize("transport", autostart.TRANSPORTS)
def test_env_alone_enabled(tmp_path, monkeypatch, transport):
    """Env var wins even with no marker file."""
    monkeypatch.setenv(f"ARENA_{transport.upper()}_AUTOSTART", "1")
    assert autostart.is_enabled(transport, tmp_path) is True


@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("TRUE", True),
    ("yes", True), ("On", True),
    ("0", False), ("no", False), ("", False), ("garbage", False),
    ("   ", False),
])
def test_env_truthy_shapes(monkeypatch, val, expected):
    monkeypatch.setenv(ENV_NG, val)
    assert autostart.is_env_enabled("ngrok") is expected


# ---------------------------------------------------------------------------
# enable/disable
# ---------------------------------------------------------------------------
def test_enable_writes_valid_json_payload(tmp_path):
    p = autostart.enable("ngrok", tmp_path, port=8765)
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["port"] == 8765
    assert data["version"] == 1
    assert isinstance(data["marked_at"], int)
    assert data["marked_at"] > 0


def test_enable_is_idempotent(tmp_path):
    autostart.enable("ngrok", tmp_path, port=8765)
    autostart.enable("ngrok", tmp_path, port=9000)
    data = json.loads(autostart.marker_path("ngrok", tmp_path).read_text())
    assert data["port"] == 9000  # last write wins


def test_enable_atomic_leaves_no_tmp(tmp_path):
    autostart.enable("cloudflared", tmp_path, port=8765)
    assert list(tmp_path.glob("*.tmp")) == []


def test_disable_returns_true_when_marker_removed(tmp_path):
    autostart.enable("tailscale", tmp_path, port=8765)
    assert autostart.disable("tailscale", tmp_path) is True
    assert not autostart.marker_path("tailscale", tmp_path).exists()


def test_disable_returns_false_when_no_marker(tmp_path):
    """rm -f semantics -- no file, no error, return False."""
    assert autostart.disable("ngrok", tmp_path) is False


def test_disable_does_not_touch_env(tmp_path, monkeypatch):
    """Docstring guarantee: disable clears the marker only. If
    the env var is set, is_enabled stays True even after disable."""
    monkeypatch.setenv(ENV_NG, "1")
    autostart.enable("ngrok", tmp_path, port=8765)
    autostart.disable("ngrok", tmp_path)
    # Marker gone, but env still set.
    assert autostart.marker_path("ngrok", tmp_path).exists() is False
    assert autostart.is_enabled("ngrok", tmp_path) is True


# ---------------------------------------------------------------------------
# state_snapshot -- shape /v1/autostart consumers expect
# ---------------------------------------------------------------------------
def test_state_snapshot_lists_every_transport(tmp_path, monkeypatch):
    for t in autostart.TRANSPORTS:
        monkeypatch.delenv(f"ARENA_{t.upper()}_AUTOSTART", raising=False)
    snap = autostart.state_snapshot(tmp_path)
    assert set(snap["transports"].keys()) == set(autostart.TRANSPORTS)
    assert list(snap["registered"]) == list(autostart.TRANSPORTS)


def test_state_snapshot_per_transport_shape(tmp_path, monkeypatch):
    monkeypatch.delenv(ENV_NG, raising=False)
    autostart.enable("ngrok", tmp_path, port=8765)
    snap = autostart.state_snapshot(tmp_path)
    ng = snap["transports"]["ngrok"]
    assert ng["enabled"] is True
    assert ng["marker"] is True
    assert ng["env_override"] is False
    assert ng["marker_path"].endswith(".ngrok_autostart")


def test_state_snapshot_env_override_surfaced(tmp_path, monkeypatch):
    """UI needs to distinguish "marker on" from "env-forced on"
    so it can render the checkbox as read-only + explain why."""
    monkeypatch.setenv(ENV_TS, "1")
    snap = autostart.state_snapshot(tmp_path)
    ts = snap["transports"]["tailscale"]
    assert ts["enabled"] is True
    assert ts["marker"] is False      # no marker file
    assert ts["env_override"] is True  # but env says yes


def test_state_snapshot_reports_missing_marker_correctly(tmp_path, monkeypatch):
    for t in autostart.TRANSPORTS:
        monkeypatch.delenv(f"ARENA_{t.upper()}_AUTOSTART", raising=False)
    snap = autostart.state_snapshot(tmp_path)
    for t in autostart.TRANSPORTS:
        assert snap["transports"][t]["enabled"] is False
        assert snap["transports"][t]["marker"] is False
        assert snap["transports"][t]["env_override"] is False


# ---------------------------------------------------------------------------
# v4.22.1 back-compat: cloudflared_autostart delegates to unified
# ---------------------------------------------------------------------------
def test_cloudflared_wrapper_delegates_to_unified(tmp_path, monkeypatch):
    """The v4.22.1 module now re-exports through the unified
    autostart. Marks written via the wrapper must be visible to
    the unified module and vice versa."""
    monkeypatch.delenv(ENV_CF, raising=False)
    from arena.admin import cloudflared_autostart as legacy
    legacy.mark_autostart(tmp_path, port=8765)
    # unified sees the same marker
    assert autostart.is_enabled("cloudflared", tmp_path) is True
    assert autostart.marker_path("cloudflared", tmp_path).exists()
    # unified can remove it
    autostart.disable("cloudflared", tmp_path)
    assert legacy.should_autostart(tmp_path) is False
