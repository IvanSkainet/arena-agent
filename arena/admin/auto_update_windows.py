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

# From a third module, not from auto_update: importing back into
# auto_update here is the circular dependency that
# used to document (removed in v4.169.1 once the cycle was gone).
from arena.admin.update_targets import replace_targets


def _bridge_port() -> int:
    """The port the mover should wait on before declaring victory."""
    raw = (os.environ.get("ARENA_PORT") or os.environ.get("PORT") or "8765").strip()
    try:
        return int(raw)
    except ValueError:
        return 8765


def _write_windows_installer(payload_root: Path, install_root: Path,
                             done_marker: Path, *, port: int | None = None) -> Path:
    """Windows can't overwrite files that a running Python process has
    open. We write a .cmd script that waits for our PID to exit, then
    robocopies (dirs) / ``copy /Y`` (files) the payload over the install
    root, then triggers a supervisor relaunch.

    The generated script must work when either ``payload_root`` or
    ``install_root`` contains parenthesis characters (see v4.60.11
    postmortem in the module docstring).
    """
    script = install_root / ".arena-update-apply.cmd"
    port = _bridge_port() if port is None else port
    pid = os.getpid()
    src = payload_root.as_posix().replace("/", "\\")
    dst = install_root.as_posix().replace("/", "\\")
    # v4.60.14: sibling log file so operators can see what the mover did
    # even when it runs detached in the background with no console.
    log = f"{dst}\\.arena-update-apply.log"
    # Lock directory, not a lock FILE: `mkdir` fails when the target
    # exists and sets errorlevel, which is the only atomic mutex cmd.exe
    # offers. A lock file via `echo > x` would happily overwrite.
    lockdir = f"{dst}\\.arena-update-apply.lock"

    # Header: wait for the bridge PID to exit before touching files.
    lines: list[str] = [
        "@echo off",
        # Deliberately do NOT enable delayed expansion — the paths below
        # can legitimately contain ``!`` characters (usernames on Windows
        # are unusual but not forbidden), and delayed expansion would eat
        # them silently.
        "setlocal disableDelayedExpansion",
        # v4.60.14: log every phase to .arena-update-apply.log next to
        # the mover script, so a failure is diagnosable from disk even
        # if the detached process is long gone.
        # v4.166.0 (bug #72): refuse to run twice. Two apply_update calls
        # -- e.g. an API caller and the Dashboard button within the same
        # minute -- each spawned a mover, and both waited on the same PID,
        # both woke on its exit, and both robocopy'd into the SAME install
        # root while both fired schtasks /Run. Observed in
        # .arena-update-apply.log: every line duplicated.
        #
        # Two concurrent copies into a live install root is how you get a
        # half-written tree, and two relaunches is how you get two bridges
        # fighting over port 8765. `2>nul` on the mkdir is the standard
        # cmd.exe mutex: the directory create is atomic, so exactly one
        # mover wins.
        f'mkdir "{lockdir}" 2>nul',
        # No `if (...)` block: a download folder like "arena-agent (2)"
        # puts a literal ')' inside the block and cmd.exe closes it early.
        # That is v4.60.11's bug, and a guard test enforces the ban -- it
        # caught this line before it shipped. `goto` costs one label.
        "if not errorlevel 1 goto :got_lock",
        f'echo [%DATE% %TIME%] another mover already running -- exiting >> "{log}"',
        "exit /b 0",
        ":got_lock",
        f'echo [%DATE% %TIME%] mover-start pid_target={pid} > "{log}"',
        # v4.60.16: log wait-loop-entry so we can distinguish "mover
        # died before the first tasklist" (Popen-detach broken) from
        # "mover looping waiting for a PID that will never die".
        f'echo [%DATE% %TIME%] wait-loop-entry >> "{log}"',
        ":wait",
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >NUL',
        "if errorlevel 1 goto :after_wait",
        "timeout /t 1 /nobreak >NUL",
        "goto :wait",
        ":after_wait",
        f'echo [%DATE% %TIME%] bridge exited, starting copy >> "{log}"',
    ]

    # Per-target copy step, expressed as a straight-line sequence of
    # ``if EXPR goto :label`` — no ``if ( ) else ( )`` blocks, so the
    # parens in ``arena-agent (2)`` never close a block early.
    # v4.169.1: discover from the payload rather than a hand-maintained
    # list. `chat_extension_firefox` shipped in v4.169.0 and reached
    # nobody because it was never named here -- and `chat_extension`
    # itself had never been updated by auto-update at all.
    # Imported here, not at module scope: auto_update imports THIS
    # module at its own bottom (see the comment there), so a top-level
    # import back into it is a circular import at init --
    for idx, name in enumerate(replace_targets(payload_root)):
        s = f"{src}\\{name}"
        d = f"{dst}\\{name}"
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
    lines.append(f'echo [%DATE% %TIME%] copy done, launching relaunch >> "{log}"')

    # Relaunch: try Scheduled Task, then start_hidden.vbs, then start_bridge.bat.
    # Again — no ``if () else ()`` blocks; only ``if EXPR goto :label``.
    task_name = (
        os.environ.get("ARENA_TASK_NAME", "").strip()
        or os.environ.get("ARENA_SERVICE_NAME", "").strip()
        or "ArenaUnifiedBridge"
    )
    vbs = f"{dst}\\start_hidden.vbs"
    bat = f"{dst}\\start_bridge.bat"
    # v4.169.21: `schtasks /Run` exiting 0 does NOT mean a process started.
    # Measured on Ivan's PC: the mover logged "relaunched via schtasks" at
    # 17:08:43, `LastTaskResult` was 0, the task went straight back to
    # `Ready` -- and no python process existed. The bridge stayed down for
    # 25 minutes across two separate updates, because the mover trusted the
    # exit code and stopped trying.
    #
    # An ONLOGON task is not reliably launchable on demand. So the exit
    # code is no longer the signal: after firing it we wait for the port
    # to answer, and fall through to the next mechanism when it does not.
    # Each step is now verified by the only thing that matters -- something
    # is listening on the port.
    # Probing the port turns out to be the fiddly part, and both obvious
    # answers were wrong on the target machine:
    #
    #   * `? :` is PowerShell 7 syntax. Windows 10 ships 5.1 -- checked,
    #     $PSVersionTable said 5 -- so that probe fails to parse and
    #     reports "down" unconditionally.
    #   * `Test-NetConnection -InformationLevel Quiet` returns $true from
    #     an interactive shell but sets errorlevel 1 from inside a .cmd
    #     against a port that is demonstrably listening. Written to disk
    #     and executed on Ivan's PC while the bridge was up: TNC_RC=1,
    #     TCPCLIENT_RC=0.
    #
    # So: a raw TcpClient connect, which answered correctly in the same
    # test. Single quotes inside, double outside -- nesting them the other
    # way is how cmd.exe eats the argument.
    probe = (
        'powershell -NoProfile -Command "$ErrorActionPreference='
        "'SilentlyContinue'; $c=New-Object Net.Sockets.TcpClient; try { "
        # DevSkim: ignore DS162092 -- probing our own port to confirm the
        # relaunch worked; v4.169.21 exists because this check was absent.
        f"$c.Connect('127.0.0.1',{port}); $ok=$c.Connected }} catch {{ "
        '$ok=$false }; $c.Close(); if ($ok) { exit 0 } else { exit 1 }"'
    )
    lines.extend([
        # 1) schtasks -- fire, then VERIFY rather than trusting errorlevel.
        f'schtasks /Run /TN "{task_name}" >NUL 2>&1',
        f'echo [%DATE% %TIME%] fired schtasks, waiting for port {port} >> "{log}"',
        'call :waitport',
        f'if not errorlevel 1 (echo [%DATE% %TIME%] relaunched via schtasks >> "{log}") & if not errorlevel 1 goto :relaunched',
        f'echo [%DATE% %TIME%] schtasks fired but nothing is listening -- next >> "{log}"',
        # 2) start_hidden.vbs
        f'if not exist "{vbs}" goto :try_bat',
        f'wscript.exe "{vbs}"',
        'call :waitport',
        f'if not errorlevel 1 (echo [%DATE% %TIME%] relaunched via start_hidden.vbs >> "{log}") & if not errorlevel 1 goto :relaunched',
        f'echo [%DATE% %TIME%] start_hidden.vbs did not bring the port up -- next >> "{log}"',
        ":try_bat",
        # 3) start_bridge.bat
        f'if not exist "{bat}" goto :no_relaunch',
        f'start "" /B "{bat}"',
        'call :waitport',
        f'if not errorlevel 1 (echo [%DATE% %TIME%] relaunched via start_bridge.bat >> "{log}") & if not errorlevel 1 goto :relaunched',
        f'echo [%DATE% %TIME%] WARN start_bridge.bat did not bring the port up >> "{log}"',
        "goto :relaunched",
        ":no_relaunch",
        f'echo [%DATE% %TIME%] WARN no relaunch mechanism found >> "{log}"',
        ":relaunched",
        # Release the mutex so a LATER update is not blocked by this one.
        # Failure is ignored on purpose: a stale lock costs one skipped
        # update with a clear log line, while `exit /b 1` here would leave
        # the operator with a mover that "failed" after copying fine.
        f'rmdir "{lockdir}" 2>nul',
        f'echo [%DATE% %TIME%] mover-done >> "{log}"',
        "endlocal",
        "exit /b 0",
        "",
        # Poll the port for ~30s. Returns errorlevel 0 once something
        # answers, 1 on timeout. Placed after `exit /b 0` so it runs only
        # when called.
        ":waitport",
        "set /a _tries=0",
        ":waitport_loop",
        f'{probe}',
        "if not errorlevel 1 exit /b 0",
        "set /a _tries+=1",
        "if %_tries% GEQ 15 exit /b 1",
        "timeout /t 2 /nobreak >NUL",
        "goto :waitport_loop",
    ])

    # Write with explicit CRLF; earlier code did ``"\r\n".join`` then
    # ``write_text`` which on Windows converts ``\n`` -> ``\r\n`` again,
    # producing ``\r\r\n`` line endings. Use ``write_bytes`` with a
    # single CRLF terminator per line to avoid the double-CR.
    script.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    return script
