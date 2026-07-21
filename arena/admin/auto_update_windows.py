"""Windows-side helpers for arena/admin/auto_update.py.

Split out in v4.60.4 to keep auto_update.py under the runtime-module
size cap (see tests/test_architecture_boundaries.py). The function
itself was introduced in v3.85.0 and its behaviour is unchanged from
that release; v4.60.4 just added the schtasks/vbs/bat relaunch tail
so the mover script actually restarts the bridge after copying files.
"""
from __future__ import annotations

import os
from pathlib import Path


def _write_windows_installer(payload_root: Path, install_root: Path,
                             done_marker: Path) -> Path:
    """Windows can't overwrite files that a running Python process has
    open. We write a .cmd script that waits for our PID to exit, then
    robocopies the payload over the install root, then touches the
    done marker so a supervisor can restart us.
    """
    script = install_root / ".arena-update-apply.cmd"
    pid = os.getpid()
    src = payload_root.as_posix().replace("/", "\\")
    dst = install_root.as_posix().replace("/", "\\")
    lines = [
        "@echo off",
        f":wait",
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >NUL',
        "if not errorlevel 1 (",
        "  timeout /t 1 /nobreak >NUL",
        "  goto wait",
        ")",
    ]
    for name in _REPLACE_TARGETS:
        s = f"{src}\\{name}"
        d = f"{dst}\\{name}"
        # /MIR mirrors a directory; for a plain file we do a copy /Y.
        lines.append(
            f'if exist "{s}\\*" ( robocopy "{s}" "{d}" /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:1 ) '
            f'else ( if exist "{s}" copy /Y "{s}" "{d}" >NUL )'
        )
    # v4.60.4: after copy, tell the operator's service supervisor to
    # relaunch us. We try Scheduled Task first (Ivan's install path),
    # then fall back to start_hidden.vbs (older installs), then to a
    # plain python invocation (last-ditch). This closes the loop so
    # the Dashboard's "Install" button actually results in a running
    # bridge on the new version, not just a successful file swap.
    task_name = os.environ.get("ARENA_TASK_NAME", "").strip() or                 os.environ.get("ARENA_SERVICE_NAME", "").strip() or                 "ArenaUnifiedBridge"
    vbs = f"{dst}\\start_hidden.vbs"
    bat = f"{dst}\\start_bridge.bat"
    lines.append(f'echo done > "{done_marker.as_posix().replace("/", chr(92))}"')
    # Try Scheduled Task
    lines.append(f'schtasks /Run /TN "{task_name}" >NUL 2>&1')
    lines.append('if not errorlevel 1 goto relaunched')
    # Fallback 1: start_hidden.vbs (installer creates this)
    lines.append(f'if exist "{vbs}" (')
    lines.append(f'  wscript.exe "{vbs}"')
    lines.append(f'  goto relaunched')
    lines.append(f')')
    # Fallback 2: start_bridge.bat
    lines.append(f'if exist "{bat}" (')
    lines.append(f'  start "" /B "{bat}"')
    lines.append(f'  goto relaunched')
    lines.append(f')')
    lines.append(':relaunched')
    script.write_text("\r\n".join(lines), encoding="utf-8")
    return script
