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

from arena.admin import auto_update, restart_capability


@pytest.fixture()
def fake_windows(monkeypatch):
    """Pretend to be Windows without touching the real platform checks."""
    monkeypatch.setattr(restart_capability, "_WIN", True)
    monkeypatch.setattr(auto_update, "_WIN", True)
    monkeypatch.setattr(restart_capability, "_scheduled_task_exists", lambda _n: False)
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
    fake_windows.setattr(auto_update.os, "_exit", lambda _c: exited.append(True))

    result = auto_update.restart_process(install_root=tmp_path)

    assert result["ok"] is False
    assert result["restart"] == "refused"
    assert exited == [], "it must not schedule an exit it cannot undo"
    assert "force=true" in result["hint"]


def test_force_stops_anyway_and_says_so(fake_windows, tmp_path: Path) -> None:
    """An operator may want the bridge down; they must not be misled."""
    fake_windows.setattr(auto_update.os, "_exit", lambda _c: None)

    result = auto_update.restart_process(install_root=tmp_path, force=True)

    assert result["ok"] is True
    assert result["forced"] is True
    assert "NOT come back" in result["hint"]


def test_hint_names_the_mechanism_that_exists(fake_windows, tmp_path: Path) -> None:
    """The old hint listed what the mover would try, and was false here."""
    (tmp_path / "start_bridge.bat").write_text("rem stub\n", encoding="utf-8")
    fake_windows.setattr(auto_update.os, "_exit", lambda _c: None)

    result = auto_update.restart_process(install_root=tmp_path)

    assert result["ok"] is True
    assert result["restart"] == "scheduled"
    assert "start_bridge.bat" in result["hint"]


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
