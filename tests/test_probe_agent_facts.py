"""Unit tests for arena/inventory/probe_agent_facts.py.

Same discipline as test_probe_sensors: monkeypatch psutil / _which
so the suite runs anywhere.
"""
from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def _mod():
    if "arena.inventory.probe_agent_facts" in sys.modules:
        del sys.modules["arena.inventory.probe_agent_facts"]
    from arena.inventory import probe_agent_facts  # noqa: E402
    return probe_agent_facts


def test_probes_return_available_dict():
    m = _mod()
    for fn_name in ("get_top_processes", "get_listening_ports",
                    "get_systemd_failed", "get_boot_time",
                    "get_kernel_modules"):
        result = getattr(m, fn_name)()
        assert isinstance(result, dict), fn_name
        assert "available" in result, fn_name
        assert isinstance(result["available"], bool)


def test_top_processes_without_psutil_reports_error():
    """When psutil import fails, probe reports error, doesn't crash."""
    m = _mod()
    import builtins
    real_import = builtins.__import__

    def fail_psutil(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("simulated: no psutil in this env")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fail_psutil):
        result = m.get_top_processes()
    assert result["available"] is False
    assert "psutil" in (result.get("error") or "").lower()


def test_boot_time_uses_psutil_boot_time():
    m = _mod()
    fake_psutil = SimpleNamespace(boot_time=lambda: 1_700_000_000)
    with patch.dict(sys.modules, {"psutil": fake_psutil}):
        result = m.get_boot_time()
    assert result["available"] is True
    assert result["boot_time_epoch"] == 1_700_000_000
    assert "T" in result["boot_time_iso"]
    assert result["uptime_seconds"] > 0


def test_systemd_failed_returns_error_on_non_linux():
    m = _mod()
    with patch.object(m, "platform") as pm:
        pm.system.return_value = "Windows"
        result = m.get_systemd_failed()
    assert result["available"] is False
    assert "linux" in (result.get("error") or "").lower()


def test_kernel_modules_returns_error_on_non_linux():
    m = _mod()
    with patch.object(m, "platform") as pm:
        pm.system.return_value = "Darwin"
        result = m.get_kernel_modules()
    assert result["available"] is False
    assert "linux" in (result.get("error") or "").lower()


def test_sections_include_new_agent_probes():
    from arena.inventory.report import SECTIONS
    names = [name for name, _ in SECTIONS]
    for expected in ("top_processes", "listening_ports", "systemd_failed",
                     "boot_time", "kernel_modules"):
        assert expected in names, f"SECTIONS missing '{expected}'"


def test_smartctl_hint_is_platform_aware():
    """v3.88.1: hint must not hardcode 'sudo setcap' on Windows/macOS."""
    from arena.inventory.probe_sensors import _smartctl_permission_hint
    with patch("arena.inventory.probe_sensors.platform") as pm:
        pm.system.return_value = "Linux"
        assert "setcap" in _smartctl_permission_hint()
        pm.system.return_value = "Darwin"
        hint_mac = _smartctl_permission_hint()
        assert "setcap" not in hint_mac
        assert "sudo" in hint_mac
        pm.system.return_value = "Windows"
        hint_win = _smartctl_permission_hint()
        assert "setcap" not in hint_win
        assert "administrator" in hint_win.lower()


def test_smartctl_hint_uses_command_v_not_hardcoded_path():
    """Regression guard against hardcoded /usr/bin/smartctl paths."""
    from arena.inventory.probe_sensors import _smartctl_permission_hint
    with patch("arena.inventory.probe_sensors.platform") as pm:
        pm.system.return_value = "Linux"
        hint = _smartctl_permission_hint()
    # Any /usr/bin, /usr/local/bin, /opt/... in the hint is a red flag.
    for bad in ("/usr/bin/smartctl", "/usr/local/bin/smartctl",
                "/opt/smartmontools"):
        assert bad not in hint, f"hint hardcodes '{bad}': {hint}"
    assert "command -v" in hint or "which " in hint


# ---------- v3.88.3 probes ------------------------------------------------

def test_new_probes_return_available_dict():
    m = _mod()
    for fn_name in ("get_containers", "get_systemd_timers", "get_network_io",
                    "get_updates_available", "get_logged_users",
                    "get_cpu_vulnerabilities"):
        result = getattr(m, fn_name)()
        assert isinstance(result, dict), fn_name
        assert "available" in result and isinstance(result["available"], bool), fn_name


def test_containers_reports_missing_runtime():
    m = _mod()
    with patch.object(m, "_which", return_value=None):
        result = m.get_containers()
    assert result["available"] is False
    assert "docker" in result["error"].lower() or "podman" in result["error"].lower()


def test_systemd_timers_off_linux():
    m = _mod()
    with patch.object(m, "platform") as pm:
        pm.system.return_value = "Darwin"
        result = m.get_systemd_timers()
    assert result["available"] is False
    assert "linux" in result["error"].lower()


def test_cpu_vulnerabilities_off_linux():
    m = _mod()
    with patch.object(m, "platform") as pm:
        pm.system.return_value = "Windows"
        result = m.get_cpu_vulnerabilities()
    assert result["available"] is False


def test_network_io_needs_psutil():
    m = _mod()
    import builtins
    real_import = builtins.__import__
    def fail_psutil(name, *args, **kwargs):
        if name == "psutil":
            raise ImportError("no psutil")
        return real_import(name, *args, **kwargs)
    with patch("builtins.__import__", side_effect=fail_psutil):
        result = m.get_network_io()
    assert result["available"] is False


def test_logged_users_uses_psutil_users():
    m = _mod()
    fake_user = SimpleNamespace(name="alice", terminal="pts/0",
                                 host="10.0.0.1", started=1700000000.0,
                                 pid=1234)
    fake_psutil = SimpleNamespace(users=lambda: [fake_user])
    with patch.dict(sys.modules, {"psutil": fake_psutil}):
        result = m.get_logged_users()
    assert result["available"] is True
    assert result["users"][0]["name"] == "alice"
    assert result["users"][0]["terminal"] == "pts/0"


def test_updates_available_reports_no_manager():
    m = _mod()
    with patch.object(m, "_which", return_value=None):
        result = m.get_updates_available()
    assert result["available"] is False
    assert "package manager" in result["error"].lower()


def test_sections_include_v883_probes():
    from arena.inventory.report import SECTIONS
    names = [name for name, _ in SECTIONS]
    for expected in ("containers", "systemd_timers", "network_io",
                     "updates_available", "logged_users",
                     "cpu_vulnerabilities"):
        assert expected in names, f"SECTIONS missing '{expected}'"
