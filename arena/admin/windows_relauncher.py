"""Detached Windows relaunch helper for manual bridge restarts.

A manual `/v1/admin/update/restart` used to check that launchers existed and
then call ``os._exit(0)`` without invoking any of them. The Scheduled Task is an
ONLOGON task; its existence does not make it react to process exit. The endpoint
therefore turned a restart into a shutdown on the live Windows host.

The helper is launched through Windows Script Host so it survives the bridge's
console/process exit. Its batch payload waits for the old PID to disappear,
then tries the concrete launchers and verifies the only observable that matters:
the bridge port is listening.
"""
from __future__ import annotations

import os
import subprocess  # nosec B404 -- fixed local launcher argv, no shell
from pathlib import Path
from typing import Any


def _bridge_port() -> int:
    raw = (os.environ.get("ARENA_PORT") or os.environ.get("PORT") or "8765").strip()
    try:
        return int(raw)
    except ValueError:
        return 8765


def write_relauncher(
    install_root: Path,
    *,
    parent_pid: int,
    port: int | None = None,
    task_name: str = "ArenaUnifiedBridge",
) -> tuple[Path, Path]:
    """Write the wait/relaunch CMD and its detached WSH shim."""
    port = _bridge_port() if port is None else int(port)
    root = str(install_root).replace("/", "\\")
    cmd = install_root / ".arena-restart.cmd"
    shim = install_root / ".arena-restart.vbs"
    log = f"{root}\\.arena-restart.log"
    hidden = f"{root}\\start_hidden.vbs"
    bat = f"{root}\\start_bridge.bat"
    probe = (
        'powershell -NoProfile -Command "$ErrorActionPreference='
        "'SilentlyContinue'; $c=New-Object Net.Sockets.TcpClient; try { "
        f"$c.Connect('127.0.0.1',{port}); $ok=$c.Connected }} catch {{ "  # DevSkim: ignore DS162092
        '$ok=$false }; $c.Close(); if ($ok) { exit 0 } else { exit 1 }"'
    )
    lines = [
        "@echo off",
        "setlocal disableDelayedExpansion",
        f'echo [%DATE% %TIME%] restart-helper waiting for pid {parent_pid} > "{log}"',
        ":wait_parent",
        f'tasklist /FI "PID eq {parent_pid}" | find "{parent_pid}" >NUL',
        "if errorlevel 1 goto :try_hidden",
        "timeout /t 1 /nobreak >NUL",
        "goto :wait_parent",
        ":try_hidden",
        f'if not exist "{hidden}" goto :try_bat',
        f'wscript.exe "{hidden}"',
        f'echo [%DATE% %TIME%] fired start_hidden.vbs >> "{log}"',
        "call :waitport",
        "if errorlevel 1 goto :try_bat",
        f'echo [%DATE% %TIME%] ready via start_hidden.vbs >> "{log}"',
        "goto :done",
        ":try_bat",
        f'if not exist "{bat}" goto :try_task',
        f'start "" /B "{bat}"',
        f'echo [%DATE% %TIME%] fired start_bridge.bat >> "{log}"',
        "call :waitport",
        "if errorlevel 1 goto :try_task",
        f'echo [%DATE% %TIME%] ready via start_bridge.bat >> "{log}"',
        "goto :done",
        ":try_task",
        f'schtasks /Run /TN "{task_name}" >NUL 2>&1',
        f'echo [%DATE% %TIME%] fired scheduled task {task_name} >> "{log}"',
        "call :waitport",
        "if errorlevel 1 goto :failed",
        f'echo [%DATE% %TIME%] ready via scheduled task >> "{log}"',
        "goto :done",
        ":failed",
        f'echo [%DATE% %TIME%] ERROR all relaunch mechanisms failed >> "{log}"',
        ":done",
        "endlocal",
        "exit /b 0",
        "",
        ":waitport",
        "set /a _tries=0",
        ":waitport_loop",
        probe,
        "if not errorlevel 1 exit /b 0",
        "set /a _tries+=1",
        "if %_tries% GEQ 15 exit /b 1",
        "timeout /t 2 /nobreak >NUL",
        "goto :waitport_loop",
    ]
    cmd.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    escaped = str(cmd).replace('"', '""')
    shim.write_bytes((
        'Set WshShell = CreateObject("WScript.Shell")\r\n'
        f'WshShell.Run "cmd /c ""{escaped}""", 0, False\r\n'
    ).encode("utf-8"))
    return cmd, shim


def prepare_relaunch(
    install_root: Path,
    *,
    parent_pid: int | None = None,
    port: int | None = None,
    task_name: str = "ArenaUnifiedBridge",
) -> dict[str, Any]:
    """Write and start the helper before the bridge schedules its exit."""
    parent_pid = os.getpid() if parent_pid is None else int(parent_pid)
    cmd, shim = write_relauncher(
        install_root,
        parent_pid=parent_pid,
        port=port,
        task_name=task_name,
    )
    subprocess.Popen(  # nosec B603 -- fixed wscript argv, no shell
        ["wscript.exe", str(shim)],
        creationflags=(
            getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_NO_WINDOW", 0)
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return {
        "prepared": True,
        "helper": str(cmd),
        "shim": str(shim),
        "parent_pid": parent_pid,
    }
