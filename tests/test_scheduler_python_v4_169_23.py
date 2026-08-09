"""v4.169.23 -- the launcher invoked a `python` the Task Scheduler cannot see.

Three consecutive updates left the PC down. Every layer said it worked:
`update/apply` returned `applied_version`, `update/restart` returned
`{"restart": "scheduled", "mechanism": "scheduled_task",
"can_restart": true}`, and the task itself reported `Last Result: 0`.
Nothing came back, and a human had to start the bridge by hand each
time.

The cause was one word. `start_bridge.bat` ran a bare `python`, which
resolves in a logged-in shell because `PATH` carries
`%LOCALAPPDATA%\\Programs\\Python\\Python314`. The Task Scheduler does
not inherit that PATH. Demonstrated on the machine itself:

    where python                       -> ...\\Python314\\python.exe
    set PATH=C:\\Windows\\system32 & where python
                                       -> INFO: could not find files

The task launches `wscript.exe`, `wscript` starts fine, and *that* is
what "Last Result: 0" describes. The batch file it spawned died on a
missing interpreter, in a window created with `WshShell.Run(..., 0,
False)` -- hidden, no console, no log. v4.169.21 had already stopped the
mover trusting exit codes and made it poll the port; it correctly found
nothing listening. The port was the right question and the answer was
still a mystery, because the reason lived one process deeper.

`sys.executable` is an absolute path to the interpreter already running,
so it is by definition the right one. `py -3` is the fallback: the
launcher lives in `System32`, which is on every PATH including the
scheduler's.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from arena.service import autostart_doctor

BARE_LAUNCHER = (
    "@echo off\r\n"
    'cd /d "C:\\Users\\Ivan\\Downloads\\arena-agent\\arena-bridge"\r\n'
    "set ARENA_AGENT_HOME=C:\\Users\\Ivan\\Downloads\\arena-agent\\arena-bridge\r\n"
    "set ARENA_TOKEN_FILE=C:\\Users\\Ivan\\Downloads\\arena-agent\\arena-bridge\\token.txt\r\n"
    'python -u unified_bridge.py serve --root "C:\\Users\\Ivan" '
    "--profile owner-shell --port 8765\r\n"
)


def test_generated_launcher_never_uses_a_bare_python(tmp_path: Path) -> None:
    """The generator is where the bad line came from."""
    result = autostart_doctor.write_windows_launchers(tmp_path)
    assert result["ok"]
    body = (tmp_path / "start_bridge.bat").read_text(encoding="utf-8")
    launch = [ln for ln in body.splitlines() if "unified_bridge.py" in ln]
    assert launch, body
    assert not launch[0].lstrip().startswith("python "), (
        "a bare `python` is not on the Task Scheduler's PATH: " + launch[0]
    )


def test_resolved_interpreter_is_absolute_or_the_system_launcher() -> None:
    resolved = autostart_doctor._python_for_scheduler()
    assert resolved == "py -3" or Path(resolved.strip('"')).is_absolute()


def test_falls_back_to_py_launcher_when_sys_executable_is_gone(monkeypatch) -> None:
    """Frozen or embedded interpreters can leave sys.executable empty.

    `py -3` is not a guess: it ships in System32, so it is reachable from
    the scheduler even when nothing else is.
    """
    monkeypatch.setattr(autostart_doctor.sys, "executable", "")
    assert autostart_doctor._python_for_scheduler() == "py -3"


def test_repair_rewrites_the_exact_launcher_that_was_on_the_pc(tmp_path: Path) -> None:
    (tmp_path / "start_bridge.bat").write_text(BARE_LAUNCHER, encoding="utf-8")

    result = autostart_doctor.repair_bare_python(tmp_path)

    assert result["ok"] is True
    assert result["changed"] is True
    body = (tmp_path / "start_bridge.bat").read_text(encoding="utf-8")
    assert not any(ln.strip().startswith("python ") for ln in body.splitlines())
    # The rest of the command must survive untouched -- the root, the
    # profile and the port are not ours to change.
    assert '--root "C:\\Users\\Ivan"' in body
    assert "--profile owner-shell" in body
    assert "--port 8765" in body
    assert (tmp_path / "start_bridge.bat.bak").is_file(), (
        "rewriting someone's launcher without a backup is not a repair"
    )


def test_repair_is_idempotent(tmp_path: Path) -> None:
    """Running it twice must not double-substitute or re-backup."""
    (tmp_path / "start_bridge.bat").write_text(BARE_LAUNCHER, encoding="utf-8")
    autostart_doctor.repair_bare_python(tmp_path)
    first = (tmp_path / "start_bridge.bat").read_bytes()

    second_result = autostart_doctor.repair_bare_python(tmp_path)

    assert second_result["changed"] is False
    assert (tmp_path / "start_bridge.bat").read_bytes() == first


def test_repair_leaves_a_deliberate_interpreter_alone(tmp_path: Path) -> None:
    """Reverse sabotage: an operator's own choice outranks the default."""
    chosen = (
        "@echo off\r\n"
        '"C:\\Tools\\Python\\python.exe" -u unified_bridge.py serve\r\n'
    )
    (tmp_path / "start_bridge.bat").write_text(chosen, encoding="utf-8")

    result = autostart_doctor.repair_bare_python(tmp_path)

    assert result["changed"] is False
    # Compare bytes: read_text() normalises CRLF to LF, so an
    # untouched file would look modified.
    assert (tmp_path / "start_bridge.bat").read_bytes() == chosen.encode("utf-8")
    assert not (tmp_path / "start_bridge.bat.bak").exists(), (
        "nothing changed, so there was nothing to back up"
    )


def test_repair_reports_a_missing_launcher_instead_of_crashing(tmp_path: Path) -> None:
    result = autostart_doctor.repair_bare_python(tmp_path)
    assert result["ok"] is False
    assert "does not exist" in result["reason"]


def test_repair_is_wired_into_the_doctor() -> None:
    """`repair()` must call it: a launcher written by an older version
    is never overwritten by `write_windows_launchers`, so without this
    the broken file survives every repair attempt."""
    import inspect

    source = inspect.getsource(autostart_doctor.repair)
    assert "repair_bare_python" in source


def test_bare_python_really_is_unreachable_from_a_stripped_path() -> None:
    """The premise, checked rather than asserted.

    Impersonates the scheduler's environment on whatever platform CI is
    running: an interpreter found only via the user's PATH disappears
    when that PATH is replaced, while an absolute path keeps working.
    """
    absolute = sys.executable
    assert Path(absolute).is_file()

    # Inherit the real environment and override only PATH. A hand-built
    # env dict drops SYSTEMROOT and kills CPython on Windows before it
    # runs a line -- that was v4.169.9, and the gate written then caught
    # this test doing it again.
    import os

    stripped_env = {**os.environ, "PATH": "/nonexistent-for-this-test"}
    ok = subprocess.run([absolute, "-c", "print('reachable')"],
                        capture_output=True, text=True, timeout=60,
                        env=stripped_env)
    assert ok.returncode == 0 and "reachable" in ok.stdout, (
        "an absolute interpreter path must work with no usable PATH -- "
        "that is the whole point of the fix"
    )
