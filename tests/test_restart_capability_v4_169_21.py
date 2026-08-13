"""v4.169.21 -- a restart that cannot restart is a shutdown.

Twice in a row, `update/restart` on Ivan's PC returned
``{"ok": true, "restart": "scheduled"}`` with a hint promising the mover
would relaunch the bridge "via Scheduled Task or start_hidden.vbs". Both
times the bridge exited and never came back; both times a human had to
start it by hand.

The mover tries three mechanisms and, finding none, writes
``WARN no relaunch mechanism found`` to a log file on a machine that is
now unreachable. None of the three existed because the install came from
unzipping a release rather than running `install.bat` -- which is the
documented quick start, not an exotic setup.

The response was the failure, not the mover: nothing checked whether a
relaunch was possible before killing the process, and the handler then
hard-coded ``restart = "scheduled"`` over whatever came back.

These tests fake Windows on Linux CI. The platform rule in AGENTS.md
exists precisely because a fix resting on OS behaviour is otherwise only
ever proven on the machine that did not have the bug.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from arena.admin import auto_update, restart_capability, restart_process as restart_process_mod


@pytest.fixture()
def fake_windows(monkeypatch):
    """Pretend to be Windows without touching the real platform checks."""
    monkeypatch.setattr(restart_capability, "_WIN", True)
    monkeypatch.setattr(auto_update, "_WIN", True)
    # v4.169.22: the implementation moved to arena.admin.restart_process
    # when auto_update crossed the 600-line ratchet. auto_update keeps a
    # forwarder, so callers are unaffected -- but a test that patches the
    # module attribute has to patch the module that now owns the code.
    monkeypatch.setattr(restart_process_mod, "_WIN", True)
    monkeypatch.setattr(restart_capability, "_scheduled_task_exists", lambda _n: False)
    monkeypatch.setattr(
        restart_process_mod,
        "_prepare_windows_relaunch",
        lambda root: {"prepared": True, "helper_root": str(root)},
    )
    return monkeypatch


def test_bare_install_root_reports_no_way_back(fake_windows, tmp_path: Path) -> None:
    """A release-zip install has none of the three artefacts."""
    info = restart_capability.describe(tmp_path)
    assert info["can_restart"] is False
    assert info["mechanism"] is None
    assert {c["mechanism"] for c in info["checked"]} == {
        "scheduled_task", "start_hidden.vbs", "start_bridge.bat"}
    # The message has to name the fix; "could not restart" sends nobody
    # anywhere.
    assert "install.bat" in info["why"]
    assert "force=true" in info["why"]


@pytest.mark.parametrize("artefact", ["start_hidden.vbs", "start_bridge.bat"])
def test_one_artefact_is_enough(fake_windows, tmp_path: Path, artefact: str) -> None:
    (tmp_path / artefact).write_text("rem stub\n", encoding="utf-8")
    info = restart_capability.describe(tmp_path)
    assert info["can_restart"] is True
    assert info["mechanism"] == artefact


def test_scheduled_task_alone_is_enough(fake_windows, tmp_path: Path) -> None:
    fake_windows.setattr(restart_capability, "_scheduled_task_exists", lambda _n: True)
    info = restart_capability.describe(tmp_path)
    assert info["can_restart"] is True
    assert info["mechanism"] == "scheduled_task"


def test_restart_refuses_when_nothing_can_relaunch(fake_windows, tmp_path: Path) -> None:
    """The whole point: do not exit into an unreachable machine."""
    exited: list[bool] = []
    fake_windows.setattr(restart_process_mod.os, "_exit", lambda _c: exited.append(True))

    result = auto_update.restart_process(install_root=tmp_path)

    assert result["ok"] is False
    assert result["restart"] == "refused"
    assert exited == [], "it must not schedule an exit it cannot undo"
    assert "force=true" in result["hint"]


def test_force_stops_anyway_and_says_so(fake_windows, tmp_path: Path) -> None:
    """An operator may want the bridge down; they must not be misled."""
    fake_windows.setattr(restart_process_mod.os, "_exit", lambda _c: None)

    result = auto_update.restart_process(install_root=tmp_path, force=True)

    assert result["ok"] is True
    assert result["forced"] is True
    assert "NOT come back" in result["hint"]


def test_restart_arms_a_detached_helper_before_promising_success(
    fake_windows, tmp_path: Path
) -> None:
    """Existing launchers are capability, not an automatic trigger."""
    (tmp_path / "start_bridge.bat").write_text("rem stub\n", encoding="utf-8")
    fake_windows.setattr(restart_process_mod.os, "_exit", lambda _c: None)

    result = auto_update.restart_process(install_root=tmp_path)

    assert result["ok"] is True
    assert result["restart"] == "scheduled"
    assert result["relauncher"]["prepared"] is True
    assert "detached helper is armed" in result["hint"]


def test_restart_refuses_when_detached_helper_cannot_be_started(
    fake_windows, tmp_path: Path
) -> None:
    (tmp_path / "start_hidden.vbs").write_text("stub\n", encoding="utf-8")
    fake_windows.setattr(
        restart_process_mod,
        "_prepare_windows_relaunch",
        lambda _root: (_ for _ in ()).throw(OSError("wscript unavailable")),
    )
    result = restart_process_mod.restart_process(install_root=tmp_path)
    assert result["ok"] is False
    assert result["restart"] == "refused"
    assert "wscript unavailable" in result["error"]
    assert "remains running" in result["hint"]


def test_auto_update_external_mover_prevents_duplicate_relauncher(
    fake_windows, tmp_path: Path
) -> None:
    (tmp_path / "start_hidden.vbs").write_text("stub\n", encoding="utf-8")
    fake_windows.setattr(
        restart_process_mod,
        "_prepare_windows_relaunch",
        lambda _root: pytest.fail("auto-update already prepared its mover"),
    )
    fake_windows.setattr(restart_process_mod.os, "_exit", lambda _c: None)
    result = restart_process_mod.restart_process(
        install_root=tmp_path,
        relauncher_prepared=True,
    )
    assert result["ok"] is True
    assert result["relauncher"] == {
        "prepared": True,
        "source": "external-update-mover",
    }


def test_posix_needs_no_capability_check(monkeypatch, tmp_path: Path) -> None:
    """Re-exec leaves no window where nothing owns the process."""
    monkeypatch.setattr(restart_capability, "_WIN", False)
    info = restart_capability.describe(tmp_path)
    assert info["can_restart"] is True
    assert info["mechanism"] == "exec"


def test_handler_does_not_overwrite_a_refusal() -> None:
    """`res["restart"] = "scheduled"` used to be unconditional.

    A refusal from restart_process was overwritten by the string
    "scheduled" on its way out, so the caller was told a restart was
    coming even when the bridge had explicitly declined to die.
    """
    source = Path(auto_update.__file__).with_name("handlers_update.py").read_text(
        encoding="utf-8")
    assert 'res["restart"] = restart_res.get("restart", "scheduled")' in source
    assert 'res["restart"] = "scheduled"' not in source


# --- the launchers can now be created, not only diagnosed -----------------

def test_repair_writes_the_launchers_instead_of_refusing(tmp_path: Path) -> None:
    """"Rerun install.bat" is not actionable from a bridge that is down.

    `repair()` used to return that string when the two launcher files
    were missing -- which is exactly the state a release-zip install is
    in, and exactly when repair is needed.
    """
    from arena.service import autostart_doctor

    result = autostart_doctor.write_windows_launchers(tmp_path, port=8765)
    assert result["ok"] is True
    assert sorted(result["created"]) == ["start_bridge.bat", "start_hidden.vbs"]

    # read_bytes, not read_text: universal-newline translation hides the
    # very thing being asserted, and a .bat with bare LF line endings
    # misbehaves under some Windows shells.
    raw = (tmp_path / "start_bridge.bat").read_bytes()
    # EVERY line, not just one: the trailing terminator alone satisfied
    # a `b"\r\n" in raw` check even with LF-joined body lines, so that
    # assertion passed while the file was wrong.
    assert b"\n" in raw
    assert b"\r\n" in raw
    lone_lf = raw.replace(b"\r\n", b"")
    assert b"\n" not in lone_lf, "a .bat needs CRLF on every line, not just the last"
    bat = raw.decode("utf-8")
    assert "unified_bridge.py serve" in bat
    assert "--port 8765" in bat
    assert str(tmp_path) in bat

    vbs = (tmp_path / "start_hidden.vbs").read_text(encoding="utf-8")
    assert "WScript.Shell" in vbs
    assert "start_bridge.bat" in vbs


def test_existing_launchers_are_never_overwritten(tmp_path: Path) -> None:
    """A hand-tuned launcher outranks the generated default."""
    from arena.service import autostart_doctor

    custom = b"@echo off\r\nrem hand written\r\n"
    (tmp_path / "start_bridge.bat").write_bytes(custom)

    result = autostart_doctor.write_windows_launchers(tmp_path)
    assert result["created"] == ["start_hidden.vbs"]
    assert (tmp_path / "start_bridge.bat").read_bytes() == custom


def test_written_launchers_satisfy_the_capability_check(tmp_path: Path,
                                                        monkeypatch) -> None:
    """The two halves must actually meet: writing them un-refuses restart."""
    from arena.service import autostart_doctor

    monkeypatch.setattr(restart_capability, "_WIN", True)
    monkeypatch.setattr(restart_capability, "_scheduled_task_exists", lambda _n: False)

    assert restart_capability.describe(tmp_path)["can_restart"] is False
    autostart_doctor.write_windows_launchers(tmp_path)
    after = restart_capability.describe(tmp_path)
    assert after["can_restart"] is True
    assert after["mechanism"] == "start_hidden.vbs"


# --- the mover trusted an exit code that meant nothing --------------------

def _mover_script(tmp_path: Path, port: int = 8765) -> str:
    from arena.admin.auto_update_windows import _write_windows_installer

    payload = tmp_path / "payload"
    (payload / "arena").mkdir(parents=True)
    (payload / "arena" / "x.py").write_text("x = 1\n", encoding="utf-8")
    install = tmp_path / "install"
    install.mkdir()
    script = _write_windows_installer(payload, install, install / "done.marker",
                                      port=port)
    return script.read_text(encoding="utf-8")


def test_mover_verifies_the_port_after_every_relaunch_attempt(tmp_path: Path) -> None:
    """`schtasks /Run` returning 0 does not mean a process started.

    Measured on the PC: the mover logged "relaunched via schtasks" at
    17:08:43, LastTaskResult was 0, the task went back to Ready -- and no
    python process existed. The bridge was down for 25 minutes because
    the exit code was treated as proof.
    """
    text = _mover_script(tmp_path)
    # One call per mechanism: schtasks, start_hidden.vbs, start_bridge.bat.
    assert text.count("call :waitport") == 3
    assert "schtasks fired but nothing is listening" in text
    assert "start_hidden.vbs did not bring the port up" in text
    # The subroutine must exist as a label on its own line.
    assert any(line.strip() == ":waitport" for line in text.splitlines())


def test_mover_probe_avoids_powershell_7_only_syntax(tmp_path: Path) -> None:
    """Windows 10 ships PowerShell 5.1; `? :` arrived in 7.

    A probe using the ternary fails to parse and reports "down" on every
    call, which would send the mover through all three mechanisms and
    then declare failure on a host where the first one worked.
    """
    text = _mover_script(tmp_path)
    probe = next(ln for ln in text.splitlines() if "TcpClient" in ln)
    assert " ? " not in probe, "PowerShell 7 ternary is unavailable on 5.1"
    assert "Test-NetConnection" not in text, (
        "Test-NetConnection -Quiet sets errorlevel 1 from inside a .cmd even "
        "against a listening port -- measured on the target machine"
    )
    assert "$c.Connected" in probe


def test_mover_probe_targets_the_configured_port(tmp_path: Path) -> None:
    text = _mover_script(tmp_path, port=9111)
    probe = next(ln for ln in text.splitlines() if "TcpClient" in ln)
    assert "9111" in probe


def test_waitport_is_bounded(tmp_path: Path) -> None:
    """An unbounded wait would hang the mover instead of falling through."""
    text = _mover_script(tmp_path)
    assert "if %_tries% GEQ 15 exit /b 1" in text


# --- v4.169.22: the thread outlived the patch and killed pytest -----------

def test_exit_hooks_are_bound_at_schedule_time_not_when_the_thread_wakes() -> None:
    """A daemon thread must not look up os._exit after the test ends.

    The failure was invisible in the worst way. A test patched
    ``os._exit``, called ``restart_process``, and finished; the thread it
    started slept half a second, by which time monkeypatch had restored
    the real function, looked it up globally, and killed pytest **mid
    run, with exit code 0**. CI read that as fifteen successful Tests
    jobs while a third of the suite never executed, no coverage.xml was
    written, and the Coverage diff job failed on a missing artifact --
    the only red square, and it pointed at the wrong thing.

    Binding the reference when the thread is scheduled makes a patched
    exit stay patched for the life of that thread.
    """
    import ast
    import inspect

    source = inspect.getsource(restart_process_mod.restart_process)
    tree = ast.parse(source.lstrip())

    late_lookups: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith("_do_"):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call):
                call = ast.unparse(inner.func)
                if call in ("os._exit", "os.execv"):
                    late_lookups.append(f"{node.name}: {call}")
    assert not late_lookups, (
        "these run on a background thread and resolve the attribute when "
        f"they wake, long after any patch is gone: {late_lookups}"
    )


def test_no_restart_thread_survives_this_test(fake_windows, tmp_path: Path) -> None:
    """Behavioural half: schedule one, then prove it cannot kill us.

    Uses a real thread and a real sleep, because the bug was entirely in
    the timing -- a mocked thread would have passed on the broken code.
    """
    import threading
    import time as _time

    exited: list[int] = []
    fake_windows.setattr(restart_process_mod.os, "_exit", lambda code: exited.append(code))
    (tmp_path / "start_bridge.bat").write_text("rem stub\n", encoding="utf-8")

    result = restart_process_mod.restart_process(install_root=tmp_path, delay_sec=0.5)
    assert result["restart"] == "scheduled"

    # Outlive the thread's sleep. If the binding regressed, the real
    # os._exit runs here and the whole session dies -- which is exactly
    # what happened in CI, so the assertion below is the polite version.
    _time.sleep(1.2)
    assert exited == [0], (
        "the scheduled exit did not reach the patched function; a real "
        "os._exit would have taken the test session with it"
    )
    assert not [t for t in threading.enumerate()
                if t.name == "arena-win-exit" and t.is_alive()]
