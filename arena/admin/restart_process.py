"""Restarting the bridge process, and refusing to when it cannot come back.

Split out of ``auto_update.py`` in v4.169.22: that module crossed the
600-line mini-monolith threshold the architecture ratchet enforces, and
the restart logic is a self-contained decision with its own failure
modes -- it deserves its own file rather than a longer one.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

_WIN = sys.platform == "win32"


def _prepare_windows_relaunch(install_root: Path) -> dict[str, Any]:
    from arena.admin import restart_capability, windows_relauncher

    return windows_relauncher.prepare_relaunch(
        install_root,
        task_name=restart_capability.task_name(),
    )


def restart_process(*, delay_sec: float = 0.5, force: bool = False,
                    install_root: Path | str | None = None,
                    relauncher_prepared: bool = False) -> dict[str, Any]:
    """Best-effort restart of the current Python process.

    On Unix we re-exec into `sys.argv`; the systemd unit picks it up
    as a clean restart.

    On Windows we first arm a detached helper, then schedule `os._exit()` in a
    background thread so the HTTP response can flush. The helper waits for this
    PID to disappear, tries the installed launchers, and verifies the port.
    Auto-update supplies `relauncher_prepared=True` because its copy mover
    already owns that lifecycle.

    Prior to v4.169.44 the manual endpoint only checked that launch artefacts
    existed; it invoked none of them. The live bridge exited and stayed down
    until the operator started `start_hidden.vbs` by hand.
    """
    if _WIN:
        # v4.169.21: verify something can bring us back BEFORE dying.
        # Twice in a row this returned {"restart": "scheduled"} on a host
        # where the mover's three relaunch mechanisms were all absent --
        # the install came from a release zip, not install.bat -- so the
        # bridge exited, the mover logged "no relaunch mechanism found",
        # and the machine stayed down until a human started it. A restart
        # that cannot restart is a shutdown, and it must not be reported
        # as the former.
        from arena.admin import restart_capability

        capability = restart_capability.describe(install_root)
        if not capability["can_restart"] and not force:
            return {
                "ok": False,
                "restart": "refused",
                "error": "no relaunch mechanism on this host",
                "capability": capability,
                "hint": ("Run install.bat to create the autostart artefacts, "
                         "or resend with force=true to stop the bridge anyway "
                         "-- it will not come back on its own."),
            }

        # `describe()` proves launchers exist; it does not invoke them. The
        # manual restart endpoint used to exit here and wait for an ONLOGON
        # Scheduled Task to notice -- it never does. Auto-update already has
        # its own detached mover, while a manual restart must prepare one now,
        # before this process becomes unreachable.
        relaunch_info: dict[str, Any] | None = None
        if capability["can_restart"] and not relauncher_prepared:
            try:
                relaunch_info = _prepare_windows_relaunch(Path(capability["install_root"]))
            except Exception as exc:
                return {
                    "ok": False,
                    "restart": "refused",
                    "error": f"could not start detached relaunch helper: {exc}",
                    "capability": capability,
                    "hint": "Bridge remains running; relaunch was not armed.",
                }
        elif relauncher_prepared:
            relaunch_info = {"prepared": True, "source": "external-update-mover"}

        # Fire-and-return: HTTP handler wants a JSON body back, so we
        # can't call os._exit synchronously here. Schedule it a moment
        # later and let the response drain.
        import threading

        # Bind the exit function NOW, not when the thread wakes up.
        #
        # v4.169.22: a test that monkeypatches ``os._exit`` and calls this
        # left a daemon thread sleeping past the end of the test. The
        # patch was undone by then, so the thread looked up the *real*
        # ``os._exit`` half a second later and killed pytest -- mid-run,
        # with exit code 0. CI read that as fifteen successful jobs while
        # a third of the suite never ran and no coverage.xml was written.
        # A late global lookup is the whole bug; capturing the reference
        # at schedule time means a patched exit stays patched.
        _exit_now = os._exit

        def _do_win_exit():
            time.sleep(max(0.5, delay_sec))
            _exit_now(0)

        threading.Thread(target=_do_win_exit, daemon=True,
                         name="arena-win-exit").start()
        return {"ok": True, "restart": "scheduled",
                "platform": "windows",
                "delay_sec": max(0.5, delay_sec),
                "capability": capability,
                "relauncher": relaunch_info,
                "forced": bool(force and not capability["can_restart"]),
                "hint": ("Bridge will exit; a detached helper is armed and "
                         "will verify the listening port after relaunch."
                         if capability["can_restart"] else
                         "Bridge will exit and will NOT come back: forced "
                         "with no relaunch mechanism available.")}
    # Give the HTTP handler a moment to flush its response before we
    # replace ourselves.
    import threading

    # Same reasoning as the Windows branch above: bind both escapes at
    # schedule time so a test that patches them is not outlived by the
    # thread it started.
    _execv_now = os.execv
    _exit_now = os._exit

    def _do_restart():
        time.sleep(max(0.05, delay_sec))
        try:
            # nosemgrep: dangerous-os-exec-tainted-env-args -- sys.argv is our own launch argv snapshot, not attacker input; this is a self-restart into the same process image after the auto-update swap.
            _execv_now(sys.executable, [sys.executable, *sys.argv])
        except Exception:
            _exit_now(0)

    threading.Thread(target=_do_restart, daemon=True,
                     name="arena-restart").start()
    return {"ok": True, "restart": "scheduled",
            "delay_sec": delay_sec, "argv": sys.argv[:1]}


__all__ = ["restart_process"]
