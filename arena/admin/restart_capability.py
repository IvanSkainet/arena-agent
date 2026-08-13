"""Can this host actually bring the bridge back after it exits?

`restart_process()` on Windows must arm a detached helper before exiting. The
helper tries `start_hidden.vbs`, `start_bridge.bat`, then the Scheduled Task and
verifies the listening port after each. When none exists, update movers write

    WARN no relaunch mechanism found

into a log nobody reads, and the machine is simply down. That happened
twice in a row on Ivan's PC: `update/apply` succeeded, `update/restart`
reported ``{"restart": "scheduled"}``, and the bridge never came back.
The response was cheerful and wrong -- the `hint` promised a relaunch
that nothing on the box was able to perform.

The install root here came from unzipping a release rather than from
`install.bat`, so none of the three artefacts were ever created. That is
not an exotic configuration; it is the documented quick-start.

So the capability is checked *before* the process is told to die, and a
host with no way back refuses the restart instead of performing it. An
operator who genuinely wants the bridge to stop can pass
``force=True`` -- what they must not get is a shutdown disguised as a
restart.
"""
from __future__ import annotations

import os
import shutil
import subprocess  # nosec B404 -- fixed argv, no shell, Windows-only probe
import sys
from pathlib import Path
from typing import Any

_WIN = sys.platform == "win32"


def task_name() -> str:
    return (
        os.environ.get("ARENA_TASK_NAME", "").strip()
        or os.environ.get("ARENA_SERVICE_NAME", "").strip()
        or "ArenaUnifiedBridge"
    )


def _scheduled_task_exists(name: str) -> bool:
    """True when schtasks knows the task.

    `schtasks /Query` exits non-zero for an unknown task, which is the
    whole signal. Any failure to run schtasks at all is reported as
    "no task" rather than raising: this runs on the path to a restart
    and must not turn a missing supervisor into a traceback.
    """
    if not shutil.which("schtasks"):
        return False
    try:
        proc = subprocess.run(  # nosec B603,B607 -- fixed argv, shell=False
            ["schtasks", "/Query", "/TN", name],
            capture_output=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def describe(install_root: Path | str | None = None) -> dict[str, Any]:
    """What, if anything, will restart the bridge after it exits."""
    root = Path(install_root) if install_root else Path.cwd()
    info: dict[str, Any] = {"platform": "windows" if _WIN else sys.platform,
                            "install_root": str(root)}

    if not _WIN:
        # POSIX re-execs itself; there is no window in which nothing owns
        # the process, so there is nothing to verify.
        info.update({"can_restart": True, "mechanism": "exec", "checked": []})
        return info

    name = task_name()
    vbs = root / "start_hidden.vbs"
    bat = root / "start_bridge.bat"
    checked = [
        # Direct launchers are more reliable for an on-demand restart. The
        # task is commonly ONLOGON: `schtasks /Run` can exit 0 without starting
        # a process, which is why the detached helper verifies the port.
        {"mechanism": "start_hidden.vbs", "detail": str(vbs),
         "available": vbs.is_file()},
        {"mechanism": "start_bridge.bat", "detail": str(bat),
         "available": bat.is_file()},
        {"mechanism": "scheduled_task", "detail": name,
         "available": _scheduled_task_exists(name)},
    ]
    available = [c for c in checked if c["available"]]
    info.update({
        "can_restart": bool(available),
        "mechanism": available[0]["mechanism"] if available else None,
        "checked": checked,
    })
    if not available:
        info["why"] = (
            "nothing on this host can relaunch the bridge: no scheduled task "
            f"named {name!r}, no start_hidden.vbs and no start_bridge.bat in "
            f"{root}. Exiting now would leave the machine unreachable until "
            "someone starts it by hand. Run install.bat to create the "
            "autostart artefacts, or pass force=true to stop anyway."
        )
    return info


__all__ = ["describe", "task_name"]
