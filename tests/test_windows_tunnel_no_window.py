"""Regression tests for Issue #183: tunnel status and version probes
must not flash visible console windows on Windows.

Asserts that cloudflared, ngrok, bore, and tailscale subprocess invocations
include CREATE_NO_WINDOW (0x08000000) on Windows.
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from arena.admin.bore import BORE_STATE, _get_bore_version, _start_bore
from arena.admin.cloudflared import (
    CLOUDFLARED_STATE,
    _get_cloudflared_version,
    _start_cloudflared,
)
from arena.admin.ngrok import (
    NGROK_STATE,
    _apply_authtoken,
    _get_ngrok_version,
    _start_ngrok,
)
from arena.admin.tailscale import sys_funnel_status, tailscale_funnel_action
from arena.util import _subprocess_kwargs


@pytest.fixture(autouse=True)
def _clean_states():
    cf_proc = CLOUDFLARED_STATE.get("proc")
    if cf_proc and hasattr(cf_proc, "kill"):
        try:
            cf_proc.kill()
        except Exception:
            pass
    CLOUDFLARED_STATE["proc"] = None
    CLOUDFLARED_STATE["url"] = ""
    CLOUDFLARED_STATE["log"].clear()

    ng_proc = NGROK_STATE.get("proc")
    if ng_proc and hasattr(ng_proc, "kill"):
        try:
            ng_proc.kill()
        except Exception:
            pass
    NGROK_STATE["proc"] = None
    NGROK_STATE["url"] = ""
    NGROK_STATE["log"].clear()

    bore_proc = BORE_STATE.get("proc")
    if bore_proc and hasattr(bore_proc, "kill"):
        try:
            bore_proc.kill()
        except Exception:
            pass
    BORE_STATE["proc"] = None
    BORE_STATE["url"] = ""
    BORE_STATE["log"].clear()
    yield


def test_subprocess_kwargs_platform_contract(monkeypatch):
    """_subprocess_kwargs returns CREATE_NO_WINDOW on win32, empty dict elsewhere."""
    monkeypatch.setattr("arena.util.sys.platform", "win32")
    assert _subprocess_kwargs() == {"creationflags": 0x08000000}

    monkeypatch.setattr("arena.util.sys.platform", "linux")
    assert _subprocess_kwargs() == {}


def test_cloudflared_version_passes_subprocess_kwargs(monkeypatch):
    monkeypatch.setattr("arena.util.sys.platform", "win32")
    mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="cloudflared version 2026.7.1"))
    monkeypatch.setattr("subprocess.run", mock_run)

    ver = _get_cloudflared_version("fake_cf")
    assert ver == "2026.7.1"
    assert mock_run.called
    kwargs = mock_run.call_args.kwargs
    assert kwargs.get("creationflags") == 0x08000000


def test_cloudflared_start_passes_subprocess_kwargs(monkeypatch):
    monkeypatch.setattr("arena.util.sys.platform", "win32")
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    mock_proc.stdout.readline.return_value = ""
    mock_popen = MagicMock(return_value=mock_proc)
    monkeypatch.setattr("subprocess.Popen", mock_popen)

    _start_cloudflared("fake_cf", 8765, subprocess_kwargs=lambda: {})
    assert mock_popen.called
    kwargs = mock_popen.call_args.kwargs
    assert kwargs.get("creationflags") == 0x08000000


def test_ngrok_version_and_authtoken_passes_subprocess_kwargs(monkeypatch):
    monkeypatch.setattr("arena.util.sys.platform", "win32")
    mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="ngrok version 3.14.0"))
    monkeypatch.setattr("subprocess.run", mock_run)

    ver = _get_ngrok_version("fake_ngrok")
    assert ver == "3.14.0"
    kwargs = mock_run.call_args.kwargs
    assert kwargs.get("creationflags") == 0x08000000

    monkeypatch.setenv("ARENA_NGROK_AUTHTOKEN", "test_tok")
    _apply_authtoken("fake_ngrok", lambda: {})
    kwargs = mock_run.call_args.kwargs
    assert kwargs.get("creationflags") == 0x08000000


def test_ngrok_start_passes_subprocess_kwargs(monkeypatch):
    monkeypatch.setattr("arena.util.sys.platform", "win32")
    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    mock_proc.stdout.readline.return_value = ""
    mock_popen = MagicMock(return_value=mock_proc)
    monkeypatch.setattr("subprocess.Popen", mock_popen)

    _start_ngrok("fake_ngrok", 8765, subprocess_kwargs=lambda: {})
    assert mock_popen.called
    kwargs = mock_popen.call_args.kwargs
    assert kwargs.get("creationflags") == 0x08000000


def test_bore_version_and_start_passes_subprocess_kwargs(monkeypatch):
    monkeypatch.setattr("arena.util.sys.platform", "win32")
    mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="bore 0.6.0"))
    monkeypatch.setattr("subprocess.run", mock_run)

    ver = _get_bore_version("fake_bore")
    assert ver == "0.6.0"
    kwargs = mock_run.call_args.kwargs
    assert kwargs.get("creationflags") == 0x08000000

    mock_proc = MagicMock()
    mock_proc.poll.return_value = 0
    mock_proc.stdout.readline.return_value = ""
    mock_popen = MagicMock(return_value=mock_proc)
    monkeypatch.setattr("subprocess.Popen", mock_popen)

    _start_bore("fake_bore", 8765, subprocess_kwargs=lambda: {})
    assert mock_popen.called
    kwargs = mock_popen.call_args.kwargs
    assert kwargs.get("creationflags") == 0x08000000


def test_tailscale_actions_pass_subprocess_kwargs(monkeypatch):
    monkeypatch.setattr("arena.util.sys.platform", "win32")
    monkeypatch.setattr("arena.admin.tailscale.which_windows_or_path", lambda *a, **kw: "fake_ts")
    mock_run = MagicMock(return_value=subprocess.CompletedProcess(args=[], returncode=0, stdout="funnel on"))
    monkeypatch.setattr("subprocess.run", mock_run)

    tailscale_funnel_action("start", 8765)
    assert mock_run.call_args.kwargs.get("creationflags") == 0x08000000

    tailscale_funnel_action("stop", 8765)
    assert mock_run.call_args.kwargs.get("creationflags") == 0x08000000

    tailscale_funnel_action("status", 8765)
    assert mock_run.call_args.kwargs.get("creationflags") == 0x08000000


def test_tailscale_sys_funnel_status_passes_subprocess_kwargs(monkeypatch):
    monkeypatch.setattr("arena.util.sys.platform", "win32")
    mock_check = MagicMock(return_value="funnel on https://test.ts.net")
    monkeypatch.setattr("subprocess.check_output", mock_check)

    res = sys_funnel_status()
    assert res.get("ok") is True
    assert mock_check.call_args.kwargs.get("creationflags") == 0x08000000
