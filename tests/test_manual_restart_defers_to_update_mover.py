"""A manual restart must not race the update mover into the same tree.

Second failure observed installing v4.169.49 on the operator's host.
The update copied correctly, yet ``/health`` still answered 4.169.48
with fresh uptime -- the files on disk were new, the running process was
old.

Two logs, one PID, written the same minute::

    .arena-update-apply.log   bridge exited, starting copy   20:11:58
    .arena-restart.log        fired start_hidden.vbs         20:11:59
    .arena-update-apply.log   copy done, launching relaunch  20:12:05

``apply`` had already armed the copy mover, which waits for the bridge
PID and relaunches *after* copying. The operator then called
``/v1/admin/update/restart``, which armed a **second** detached waiter on
the same PID. That one had no copying to do, so it won by six seconds
and started Python against a tree robocopy was still rewriting.

The apply handler already knows this hazard -- it passes
``relauncher_prepared=True`` on Windows precisely so a second helper is
not armed. The manual endpoint passed nothing, so it always armed one.

A pending mover owns the relaunch. When one is live, the manual restart
must let it do its job rather than starting the old code mid-copy.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from arena.admin import restart_process as _rp


class _Recorder:
    """Stands in for the detached-helper spawn."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, install_root: Path) -> dict[str, object]:
        self.calls += 1
        return {"prepared": True, "helper": str(install_root)}


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_rp, "_WIN", True)


@pytest.fixture
def install_root(tmp_path: Path) -> Path:
    root = tmp_path / "arena-bridge"
    root.mkdir()
    (root / "start_hidden.vbs").write_text("shim", encoding="utf-8")
    (root / "start_bridge.bat").write_text("bat", encoding="utf-8")
    return root


@pytest.fixture
def no_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Never let a scheduled ``os._exit`` outlive the test (v4.169.22)."""
    monkeypatch.setattr(_rp.os, "_exit", lambda code: None)


@pytest.fixture
def capability(monkeypatch: pytest.MonkeyPatch, install_root: Path):
    from arena.admin import restart_capability

    monkeypatch.setattr(
        restart_capability, "describe",
        lambda root=None: {
            "can_restart": True,
            "install_root": str(install_root),
            "platform": "windows",
            "mechanism": "start_hidden.vbs",
        },
    )
    return restart_capability


def _arm_pending_mover(install_root: Path) -> Path:
    """Create the artefacts a live copy mover leaves behind."""
    lock = install_root / ".arena-update-apply.lock"
    lock.mkdir()
    (install_root / ".arena-update-apply.cmd").write_text("@echo off", encoding="utf-8")
    return lock


@pytest.mark.skipif(sys.platform == "win32", reason="patches _WIN on posix hosts")
def test_manual_restart_does_not_arm_a_second_helper_while_a_mover_holds_the_lock(
    windows, install_root, capability, no_exit, monkeypatch,
) -> None:
    _arm_pending_mover(install_root)
    recorder = _Recorder()
    monkeypatch.setattr(_rp, "_prepare_windows_relaunch", recorder)

    res = _rp.restart_process(install_root=install_root)

    assert recorder.calls == 0, (
        "a second relaunch helper was armed while the update mover was "
        "still copying -- this is the v4.169.49 race"
    )
    assert res["ok"] is True
    # The relauncher record must still report an armed relaunch -- the caller
    # uses it to distinguish "someone will bring me back" from "nobody will".
    assert res["relauncher"] == {"prepared": True, "source": "update-mover"}


@pytest.mark.skipif(sys.platform == "win32", reason="patches _WIN on posix hosts")
def test_the_caller_is_told_the_mover_owns_the_relaunch(
    windows, install_root, capability, no_exit, monkeypatch,
) -> None:
    _arm_pending_mover(install_root)
    monkeypatch.setattr(_rp, "_prepare_windows_relaunch", _Recorder())

    res = _rp.restart_process(install_root=install_root)

    assert res["restart"] == "scheduled"
    assert "mover" in res["hint"].lower(), res["hint"]


@pytest.mark.skipif(sys.platform == "win32", reason="patches _WIN on posix hosts")
def test_a_normal_restart_still_arms_its_own_helper(
    windows, install_root, capability, no_exit, monkeypatch,
) -> None:
    """No mover pending: the manual restart must still relaunch us."""
    recorder = _Recorder()
    monkeypatch.setattr(_rp, "_prepare_windows_relaunch", recorder)

    res = _rp.restart_process(install_root=install_root)

    assert recorder.calls == 1, "manual restart stopped arming its helper"
    assert res["ok"] is True


def test_an_unknown_install_root_is_never_treated_as_a_pending_mover() -> None:
    """No install root means no evidence -- and no evidence must not mean 'yes'.

    Answering True here would tell the caller somebody else owns the
    relaunch when nothing does, and the bridge would exit for good. A
    surviving mutant (`return True`) proved nothing covered this.
    """
    assert _rp._update_mover_pending(None) is False


def test_a_root_with_no_mover_artefacts_is_not_pending(tmp_path: Path) -> None:
    assert _rp._update_mover_pending(tmp_path) is False


def test_a_string_install_root_is_accepted(tmp_path: Path) -> None:
    """``capability["install_root"]`` is a str, not a Path."""
    (tmp_path / ".arena-update-apply.lock").mkdir()
    (tmp_path / ".arena-update-apply.cmd").write_text("@echo off", encoding="utf-8")
    assert _rp._update_mover_pending(str(tmp_path)) is True


def test_a_mover_script_without_a_lock_is_not_pending(tmp_path: Path) -> None:
    """A leftover script from a finished update must not block restarts."""
    (tmp_path / ".arena-update-apply.cmd").write_text("@echo off", encoding="utf-8")
    assert _rp._update_mover_pending(tmp_path) is False


@pytest.mark.skipif(sys.platform == "win32", reason="patches _WIN on posix hosts")
def test_a_stale_lock_without_a_mover_script_does_not_block_restart(
    windows, install_root, capability, no_exit, monkeypatch,
) -> None:
    """A lock left by a crashed mover must not disable manual restart forever."""
    (install_root / ".arena-update-apply.lock").mkdir()
    recorder = _Recorder()
    monkeypatch.setattr(_rp, "_prepare_windows_relaunch", recorder)

    res = _rp.restart_process(install_root=install_root)

    assert recorder.calls == 1, (
        "a lock with no mover script disabled the relaunch helper; the host "
        "would exit and never come back"
    )
    assert res["ok"] is True
