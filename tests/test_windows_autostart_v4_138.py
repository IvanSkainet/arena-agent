"""v4.138.0 -- Windows scheduled-task autostart is per-user logon."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALL_BAT = ROOT / "install.bat"


def _install_bat() -> str:
    return INSTALL_BAT.read_text(encoding="utf-8")


def test_windows_fallback_scheduled_task_uses_onlogon_not_onstart_with_user():
    text = _install_bat().lower()
    assert '/sc onlogon' in text
    assert '/sc onstart /ru "%username%"' not in text
    assert 'onstart + /ru %%username%% is unreliable after reboot' in text


def test_windows_fallback_scheduled_task_has_non_highest_retry():
    text = _install_bat().lower()
    assert '/rl highest' in text
    assert 'retrying without /rl highest' in text
    assert 'per-user logon scheduled task installed and started' in text
