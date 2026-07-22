"""Windows-side helpers for arena/admin/auto_update.py.

Split out in v4.60.4 to keep auto_update.py under the runtime-module
size cap (see tests/test_architecture_boundaries.py). The function
itself was introduced in v3.85.0. v4.60.4 added the schtasks/vbs/bat
relaunch tail so the mover script actually restarts the bridge after
copying files.

v4.60.11 rewrite: the previous mover was structured as
``if exist "SRC\\*" ( robocopy ... ) else ( copy ... )`` — nice and
compact, but Windows batch parses parenthesised blocks up-front. When
the install root or the temp payload path contained ``(`` or ``)``
(anywhere in the substring the parser sees), the ``)`` inside the path
closed the block early and everything after leaked into the enclosing
scope. Ivan's install into ``C:\\Users\\Ivan\\Downloads\\arena-agent (2)\\``
made the mover silently exit before copying anything, and
``apply_update`` returned ``"swapped": null``.

The rewrite uses ``if <cond> goto :label`` sequences instead of
``if () else ()`` blocks. ``goto`` targets are unaffected by paren
characters in path values, so the mover works with any install path.
"""
from __future__ import annotations

import os
from pathlib import Path

from arena.admin.auto_update import _REPLACE_TARGETS


def _write_windows_installer(payload_root: Path, install_root: Path,
                             done_marker: Path) -> Path:
    """Windows can't overwrite files that a running Python process has
    open. We write a .cmd script that waits for our PID to exit, then
    robocopies (dirs) / ``copy /Y`` (files) the payload over the install
    root, then triggers a supervisor relaunch.

    The generated script must work when either ``payload_root`` or
    ``install_root`` contains parenthesis characters (see v4.60.11
    postmortem in the module docstring).
    """
    script = install_root / ".arena-update-apply.cmd"
    pid = os.getpid()
    src = payload_root.as_posix().replace("/", "\\")
    dst = install_root.as_posix().replace("/", "\\")

    # Header: wait for the bridge PID to exit before touching files.
    lines: list[str] = [
        "@echo off",
        # Deliberately do NOT enable delayed expansion — the paths below
        # can legitimately contain ``!`` characters (usernames on Windows
        # are unusual but not forbidden), and delayed expansion would eat
        # them silently.
        "setlocal disableDelayedExpansion",
        ":wait",
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >NUL',
        "if errorlevel 1 goto :after_wait",
        "timeout /t 1 /nobreak >NUL",
        "goto :wait",
        ":after_wait",
    ]

    # Per-target copy step, expressed as a straight-line sequence of
    # ``if EXPR goto :label`` — no ``if ( ) else ( )`` blocks, so the
    # parens in ``arena-agent (2)`` never close a block early.
    for idx, name in enumerate(_REPLACE_TARGETS):
        s = f"{src}\\{name}"
        d = f"{dst}\\{name}"
        skip = f"skip_{idx}"
        as_file = f"as_file_{idx}"
        nxt = f"next_{idx}"
        lines.extend([
            f'rem ---- target {idx}: {name} ----',
            # If the source doesn't exist at all, skip.
            f'if not exist "{s}" goto :{nxt}',
            # If the source has children (i.e. it's a directory with contents),
            # use robocopy. Otherwise treat as a plain file and use copy /Y.
            f'if not exist "{s}\\*" goto :{as_file}',
            f'robocopy "{s}" "{d}" /MIR /NFL /NDL /NJH /NJS /NP /R:2 /W:1 >NUL',
            f'goto :{nxt}',
            f':{as_file}',
            f'copy /Y "{s}" "{d}" >NUL',
            f':{nxt}',
        ])

    # Mark done so any watcher can observe completion.
    done_win = done_marker.as_posix().replace("/", "\\")
    lines.append(f'echo done > "{done_win}"')

    # Relaunch: try Scheduled Task, then start_hidden.vbs, then start_bridge.bat.
    # Again — no ``if () else ()`` blocks; only ``if EXPR goto :label``.
    task_name = (
        os.environ.get("ARENA_TASK_NAME", "").strip()
        or os.environ.get("ARENA_SERVICE_NAME", "").strip()
        or "ArenaUnifiedBridge"
    )
    vbs = f"{dst}\\start_hidden.vbs"
    bat = f"{dst}\\start_bridge.bat"
    lines.extend([
        # 1) schtasks
        f'schtasks /Run /TN "{task_name}" >NUL 2>&1',
        "if not errorlevel 1 goto :relaunched",
        # 2) start_hidden.vbs
        f'if not exist "{vbs}" goto :try_bat',
        f'wscript.exe "{vbs}"',
        "goto :relaunched",
        ":try_bat",
        # 3) start_bridge.bat
        f'if not exist "{bat}" goto :relaunched',
        f'start "" /B "{bat}"',
        ":relaunched",
        "endlocal",
        "exit /b 0",
    ])

    # Write with explicit CRLF; earlier code did ``"\r\n".join`` then
    # ``write_text`` which on Windows converts ``\n`` -> ``\r\n`` again,
    # producing ``\r\r\n`` line endings. Use ``write_bytes`` with a
    # single CRLF terminator per line to avoid the double-CR.
    script.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    return script
