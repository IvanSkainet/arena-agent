"""v4.169.44 manual Windows restart must actually arm a relaunch."""
from __future__ import annotations

import re
from pathlib import Path

from arena.admin import auto_update, restart_process, windows_relauncher


def test_relauncher_waits_for_parent_and_verifies_each_mechanism(tmp_path: Path) -> None:
    root = tmp_path / "arena-agent (2)"
    root.mkdir()
    cmd, shim = windows_relauncher.write_relauncher(
        root,
        parent_pid=15300,
        port=9111,
        task_name="Arena Test Task",
    )
    raw = cmd.read_bytes()
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")
    text = raw.decode("utf-8")
    assert 'tasklist /FI "PID eq 15300"' in text
    assert text.index(":wait_parent") < text.index(":try_hidden")
    assert text.index(":try_hidden") < text.index(":try_bat") < text.index(":try_task")
    assert text.count("call :waitport") == 3
    assert "9111" in next(line for line in text.splitlines() if "TcpClient" in line)
    assert "if %_tries% GEQ 15 exit /b 1" in text
    assert 'schtasks /Run /TN "Arena Test Task"' in text
    unsafe_if_blocks = []
    for line in text.splitlines():
        structural = re.sub(r'"[^"]*"', '""', line)
        if structural.lstrip().lower().startswith("if ") and "(" in structural:
            unsafe_if_blocks.append(line)
    assert not unsafe_if_blocks
    assert "WScript.Shell" in shim.read_text(encoding="utf-8")
    assert str(cmd) in shim.read_text(encoding="utf-8")


def test_prepare_relaunch_starts_detached_wscript(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[tuple[list[str], dict]] = []

    class FakePopen:
        def __init__(self, argv, **kwargs) -> None:
            calls.append((argv, kwargs))

    monkeypatch.setattr(windows_relauncher.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(
        windows_relauncher.subprocess, "DETACHED_PROCESS", 0x8, raising=False
    )
    monkeypatch.setattr(
        windows_relauncher.subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200, raising=False
    )
    monkeypatch.setattr(
        windows_relauncher.subprocess, "CREATE_NO_WINDOW", 0x8000000, raising=False
    )

    result = windows_relauncher.prepare_relaunch(tmp_path, parent_pid=42)

    assert result["prepared"] is True
    assert result["parent_pid"] == 42
    assert calls[0][0] == ["wscript.exe", str(tmp_path / ".arena-restart.vbs")]
    assert calls[0][1]["creationflags"] == 0x8000208
    assert calls[0][1]["close_fds"] is True


def test_auto_update_forwarder_preserves_external_mover_flag(monkeypatch) -> None:
    seen: dict = {}

    def fake_restart(**kwargs):
        seen.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(restart_process, "restart_process", fake_restart)
    result = auto_update.restart_process(
        delay_sec=1.0,
        force=False,
        install_root="X:/arena",
        relauncher_prepared=True,
    )
    assert result == {"ok": True}
    assert seen == {
        "delay_sec": 1.0,
        "force": False,
        "install_root": "X:/arena",
        "relauncher_prepared": True,
    }
