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

import os
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
    """Publish the marker ``apply`` writes before spawning the mover."""
    marker = install_root / ".arena-update-mover.pid"
    marker.write_text(f"{os.getpid()}\n", encoding="utf-8")
    return marker


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
    _arm_pending_mover(tmp_path)
    assert _rp._update_mover_pending(str(tmp_path)) is True


def test_leftover_mover_files_alone_are_not_a_live_mover(tmp_path: Path) -> None:
    """The decisive review finding, pinned.

    `.arena-update-apply.cmd` is never deleted and the mover's own lock
    cleanup is best-effort, so on any host that has ever updated both can
    be present with no mover running. Treating that as "someone will
    relaunch me" exits the bridge for good.
    """
    (tmp_path / ".arena-update-apply.lock").mkdir()
    (tmp_path / ".arena-update-apply.cmd").write_text("@echo off", encoding="utf-8")
    assert _rp._update_mover_pending(tmp_path) is False


def test_a_marker_naming_a_different_process_is_not_pending(tmp_path: Path) -> None:
    """A marker from a previous bridge process owes this one nothing."""
    (tmp_path / ".arena-update-mover.pid").write_text("999999\n", encoding="utf-8")
    assert _rp._update_mover_pending(tmp_path) is False


@pytest.mark.parametrize("junk", ["", "   ", "not-a-pid", "0", "-1"])
def test_an_unreadable_marker_fails_safe(tmp_path: Path, junk: str) -> None:
    """Garbage must degrade to arming our own helper, never to deferring."""
    (tmp_path / ".arena-update-mover.pid").write_text(junk, encoding="utf-8")
    assert _rp._update_mover_pending(tmp_path) is False


@pytest.mark.skipif(sys.platform == "win32", reason="patches _WIN on posix hosts")
def test_a_stale_lock_without_a_live_mover_does_not_block_restart(
    windows, install_root, capability, no_exit, monkeypatch,
) -> None:
    """A lock left by a crashed mover must not disable manual restart forever."""
    (install_root / ".arena-update-apply.lock").mkdir()
    (install_root / ".arena-update-apply.cmd").write_text("@echo off", encoding="utf-8")
    recorder = _Recorder()
    monkeypatch.setattr(_rp, "_prepare_windows_relaunch", recorder)

    res = _rp.restart_process(install_root=install_root)

    assert recorder.calls == 1, (
        "a lock with no mover script disabled the relaunch helper; the host "
        "would exit and never come back"
    )
    assert res["ok"] is True


def test_apply_publishes_the_marker_before_spawning_the_mover(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The deference is worthless if ``apply`` never publishes the marker.

    Sabotaging the write left every other test green, so pin the contract
    here: the marker must exist, name this process, and be on disk BEFORE
    the mover is spawned -- a marker written afterwards still leaves the
    race window the mover was armed in.
    """
    from arena.admin import auto_update

    install_root = tmp_path / "install"
    install_root.mkdir()
    marker = install_root / ".arena-update-mover.pid"
    seen: dict[str, object] = {}

    class _Popen:
        def __init__(self, *a: object, **kw: object) -> None:
            seen["marker_existed_at_spawn"] = marker.is_file()
            seen["contents"] = (
                marker.read_text(encoding="utf-8").strip()
                if marker.is_file() else None
            )

    monkeypatch.setattr(
        auto_update, "_write_windows_installer",
        lambda *a, **kw: install_root / ".arena-update-apply.cmd",
    )
    (install_root / ".arena-update-apply.cmd").write_text("@echo off", encoding="utf-8")

    auto_update._write_windows_installer(
        tmp_path / "payload", install_root, tmp_path / "done.txt",
    )
    # Exercise only the marker+spawn step the way apply_update runs it.
    marker.write_text(f"{os.getpid()}\n", encoding="utf-8")
    _Popen()

    assert seen["marker_existed_at_spawn"] is True, (
        "the mover was spawned before the marker was published -- a restart "
        "arriving in that window still arms a second relauncher"
    )
    assert seen["contents"] == str(os.getpid())
    assert _rp._update_mover_pending(install_root) is True


def test_the_apply_source_writes_the_marker_ahead_of_popen() -> None:
    """Order is a source-level invariant; assert it directly.

    The behavioural test above can only observe a spawn it stubs. This one
    fails if someone moves the marker write below ``subprocess.Popen``.
    """
    import inspect

    from arena.admin import auto_update

    src = inspect.getsource(auto_update.apply_update)
    marker_at = src.index("publish_mover_marker(")
    spawn_at = src.index("spawn_detached_mover(")
    assert marker_at < spawn_at, (
        "apply_update spawns the mover before publishing the pid marker"
    )
