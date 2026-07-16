"""Tests for the v4.1.1 smartctl sudo-fallback logic."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.inventory import probe_sensors as ps


def _stub_run(returns):
    """Return a _run replacement that pops from ``returns`` per call."""
    calls: list[list[str]] = []

    def _fake_run(cmd, timeout=8):
        calls.append(cmd)
        return returns.pop(0) if returns else ""

    return _fake_run, calls


# --- direct call succeeds: no sudo attempted -----------------------

def test_direct_call_success_no_sudo(monkeypatch):
    fake, calls = _stub_run(['{"smartctl":{"exit_status":0}}'])
    monkeypatch.setattr(ps, "_run", fake)
    result = ps._smartctl_run(["-H", "/dev/sda"])
    assert calls == [["smartctl", "-H", "/dev/sda"]]
    assert "exit_status" in result


# --- permission-denied triggers sudo retry ------------------------

def test_permission_denied_triggers_sudo_retry(monkeypatch):
    perm_err = 'Smartctl open device: /dev/sda failed: Permission denied'
    success = 'SMART overall-health self-assessment test result: PASSED'
    fake, calls = _stub_run([perm_err, success])
    monkeypatch.setattr(ps, "_run", fake)
    monkeypatch.setattr(ps.platform, "system", lambda: "Linux")
    result = ps._smartctl_run(["-H", "/dev/sda"])
    assert len(calls) == 2
    assert calls[0] == ["smartctl", "-H", "/dev/sda"]
    assert calls[1] == ["sudo", "-n", "smartctl", "-H", "/dev/sda"]
    assert "PASSED" in result


# --- sudo also fails: caller sees original error + hint --------

def test_sudo_also_fails_returns_original(monkeypatch):
    perm_err = 'Smartctl open device: /dev/sda failed: Permission denied'
    fake, calls = _stub_run([perm_err, perm_err])
    monkeypatch.setattr(ps, "_run", fake)
    monkeypatch.setattr(ps.platform, "system", lambda: "Linux")
    result = ps._smartctl_run(["-H", "/dev/sda"])
    # Still returns something so the caller's json.loads / hint
    # rendering path still runs and shows the operator the fix.
    assert result == perm_err
    assert len(calls) == 2  # both attempts made


# --- sudo -n silently unavailable (returns empty): also OK -----

def test_sudo_returns_empty_falls_back_to_original(monkeypatch):
    perm_err = 'Smartctl open device: /dev/sda failed: Permission denied'
    fake, calls = _stub_run([perm_err, ""])
    monkeypatch.setattr(ps, "_run", fake)
    monkeypatch.setattr(ps.platform, "system", lambda: "Linux")
    result = ps._smartctl_run(["-H", "/dev/sda"])
    assert result == perm_err


# --- non-Linux: no sudo attempt --------------------------------

def test_non_linux_never_tries_sudo(monkeypatch):
    perm_err = 'Smartctl open device failed: Permission denied'
    fake, calls = _stub_run([perm_err])
    monkeypatch.setattr(ps, "_run", fake)
    monkeypatch.setattr(ps.platform, "system", lambda: "Windows")
    result = ps._smartctl_run(["-H", "/dev/sda"])
    assert len(calls) == 1
    assert calls[0][0] == "smartctl"  # no "sudo"


# --- empty output: no retry, return empty -------------------

def test_empty_output_no_retry(monkeypatch):
    fake, calls = _stub_run([""])
    monkeypatch.setattr(ps, "_run", fake)
    result = ps._smartctl_run(["-H", "/dev/sda"])
    assert result == ""
    assert len(calls) == 1
