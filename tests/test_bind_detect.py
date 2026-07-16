"""Tests for arena.bind_detect (v4.1.0)."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.bind_detect import resolve_bind


# --- explicit bind is always preserved -------------------------------

def test_explicit_ipv4_returned_verbatim():
    addr, reason = resolve_bind("10.5.1.42")
    assert addr == "10.5.1.42"
    assert reason == "explicit"


def test_explicit_0_0_0_0_returned_verbatim():
    addr, reason = resolve_bind("0.0.0.0")
    assert addr == "0.0.0.0"
    assert reason == "explicit"


def test_default_loopback_without_optin_stays_loopback(monkeypatch):
    monkeypatch.delenv("ARENA_AUTO_BIND", raising=False)
    addr, reason = resolve_bind("127.0.0.1")
    assert addr == "127.0.0.1"
    assert "default" in reason.lower()


# --- auto mode: detect overlays --------------------------------------

def test_auto_mode_finds_tailscale():
    with patch("arena.bind_detect._list_interface_names",
               return_value=["lo", "eth0", "tailscale0"]):
        addr, reason = resolve_bind("auto")
    assert addr == "0.0.0.0"
    assert "Tailscale" in reason
    assert "tailscale0" in reason


def test_auto_mode_finds_zerotier():
    with patch("arena.bind_detect._list_interface_names",
               return_value=["lo", "eth0", "zt7nnwiuux"]):
        addr, reason = resolve_bind("auto")
    assert addr == "0.0.0.0"
    assert "ZeroTier" in reason
    assert "zt7nnwiuux" in reason


def test_auto_mode_reports_both_overlays_when_present():
    with patch("arena.bind_detect._list_interface_names",
               return_value=["lo", "tailscale0", "zt7nnwiuux"]):
        addr, reason = resolve_bind("auto")
    assert addr == "0.0.0.0"
    assert "Tailscale" in reason
    assert "ZeroTier" in reason


def test_auto_mode_without_overlay_stays_loopback():
    """No Tailscale, no ZeroTier -> auto keeps loopback (no security regression)."""
    with patch("arena.bind_detect._list_interface_names",
               return_value=["lo", "eth0", "wlp3s0"]):
        addr, reason = resolve_bind("auto")
    assert addr == "127.0.0.1"
    assert "no overlay" in reason.lower()


def test_env_optin_triggers_auto_on_default_bind(monkeypatch):
    """ARENA_AUTO_BIND=1 lets operators enable auto-widening without
    changing their command line -- helpful when the bridge is behind
    a systemd unit or nssm wrapper they don't want to touch."""
    monkeypatch.setenv("ARENA_AUTO_BIND", "1")
    with patch("arena.bind_detect._list_interface_names",
               return_value=["lo", "tailscale0"]):
        addr, _ = resolve_bind("127.0.0.1")
    assert addr == "0.0.0.0"


def test_env_optin_does_not_override_explicit_bind(monkeypatch):
    monkeypatch.setenv("ARENA_AUTO_BIND", "1")
    with patch("arena.bind_detect._list_interface_names",
               return_value=["lo", "tailscale0"]):
        addr, reason = resolve_bind("10.5.1.42")
    assert addr == "10.5.1.42"
    assert reason == "explicit"


# --- Windows/utun prefixes ------------------------------------------

def test_utun_matches_tailscale_prefix_on_macos():
    with patch("arena.bind_detect._list_interface_names",
               return_value=["lo0", "en0", "utun3"]):
        addr, reason = resolve_bind("auto")
    assert addr == "0.0.0.0"
    assert "utun3" in reason


# --- log callback is invoked ---------------------------------------------

def test_log_callback_receives_reason():
    calls: list[tuple] = []
    def _log(fmt, *args):
        calls.append((fmt % args) if args else fmt)
    with patch("arena.bind_detect._list_interface_names",
               return_value=["lo", "tailscale0"]):
        resolve_bind("auto", log_info=_log)
    assert calls
    assert "Tailscale" in calls[0]
