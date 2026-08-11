"""v4.169.38 -- Uninstaller & installer process kill safety tests.

Guards against killing client processes (e.g. browser instances connected
to the bridge port) during uninstallation, installation, or CDP cleanup:
* `uninstall.bat` and `install.bat` filter netstat output strictly by `LISTENING`;
* `uninstall.sh` and `install.sh` pass `-sTCP:LISTEN` to `lsof`;
* `arena/browser/cdp_client/process_helpers.py` passes `-sTCP:LISTEN` to `lsof`;
* `_kill_port_processes` subprocess argv verification.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.browser.cdp_client.process_helpers as ph  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_uninstall_bat_filters_netstat_by_listening():
    bat = (ROOT / "uninstall.bat").read_bytes().decode("utf-8", errors="ignore")
    # Must contain netstat pipeline with LISTENING filter
    assert "findstr /I \"LISTENING\"" in bat or "findstr \"LISTENING\"" in bat
    # Must NOT have raw netstat findstr without LISTENING filter
    assert 'for /f "tokens=5" %%P in (\'netstat -ano 2^>nul ^| findstr ":%PORT% "\')' not in bat


def test_install_bat_filters_netstat_by_listening():
    bat = (ROOT / "install.bat").read_bytes().decode("utf-8", errors="ignore")
    assert "findstr /I \"LISTENING\"" in bat or "findstr \"LISTENING\"" in bat
    assert 'for /f "tokens=5" %%P in (\'netstat -ano 2^>nul ^| findstr ":%PORT% "\')' not in bat


def test_uninstall_sh_uses_listen_filter_in_lsof():
    sh = (ROOT / "uninstall.sh").read_text(encoding="utf-8")
    assert "lsof -ti -sTCP:LISTEN" in sh
    assert 'lsof -ti :"$PORT"' not in sh


def test_install_sh_uses_listen_filter_in_lsof():
    sh = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert "lsof -ti -sTCP:LISTEN" in sh


def test_kill_port_processes_passes_listen_filter_to_lsof(monkeypatch):
    seen_calls = []

    def _mock_run(argv, **kwargs):
        seen_calls.append(list(argv))
        if argv[0] == "ss":
            raise FileNotFoundError("no ss")
        if argv[0] == "lsof":
            return subprocess.CompletedProcess(argv, 0, stdout="12345\n", stderr="")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(ph.subprocess, "run", _mock_run)
    monkeypatch.setattr(ph.os, "kill", lambda pid, sig: None)
    monkeypatch.setattr(ph.os, "getpid", lambda: 99999)

    killed = ph._kill_port_processes(9222)
    assert killed == [12345]
    assert any(
        call[0] == "lsof" and "-sTCP:LISTEN" in call and ":9222" in call
        for call in seen_calls
    )
