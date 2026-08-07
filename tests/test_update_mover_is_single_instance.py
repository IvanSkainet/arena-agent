"""Two update installers must not copy into the same tree at once.

Bug #72, found by reading `.arena-update-apply.log` on the operator's
machine after a real update. Every line appeared **twice**:

    bridge exited, starting copy   x2
    copy done, launching relaunch  x2
    relaunched via schtasks        x2

Two movers had been spawned -- an API call and the Dashboard button
within the same minute, both perfectly legitimate. Each waited on the
same bridge PID, both woke when it exited, and both ran `robocopy` into
the live install root while both fired `schtasks /Run`.

The update happened to survive. Two concurrent copies into a tree that is
being replaced is how you get a half-written install, and two relaunches
is how you get two bridges fighting over port 8765 -- neither of which
announces itself politely.

`mkdir` is the mutex because it is the only atomic one cmd.exe offers:
creating a directory that exists fails and sets errorlevel. A lock
*file* written with `echo >` would silently overwrite and both movers
would proceed.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

import arena.admin.auto_update as _au  # noqa: F401 -- breaks a circular import
from arena.admin.auto_update_windows import _write_windows_installer


@pytest.fixture
def script_text() -> str:
    root = pathlib.Path(tempfile.mkdtemp())
    (root / "src").mkdir()
    (root / "dst").mkdir()
    script = _write_windows_installer(root / "src", root / "dst",
                                      root / "done.txt")
    return script.read_text(encoding="utf-8", errors="replace")


def test_the_mover_takes_a_lock_before_doing_anything(script_text):
    assert "mkdir" in script_text, "no mutex at all"
    assert ".arena-update-apply.lock" in script_text
    assert script_text.index("mkdir") < script_text.index("mover-start"), (
        "the lock is taken after work has already begun"
    )


def test_a_second_mover_exits_instead_of_copying(script_text):
    assert "another mover already running" in script_text
    lock_at = script_text.index("mkdir")
    exit_at = script_text.index("exit /b 0")
    copy_at = script_text.index("robocopy")
    assert lock_at < exit_at < copy_at, (
        "the loser must exit before reaching the copy, not after"
    )


def test_the_lock_is_a_directory_not_a_file(script_text):
    """`echo > lock` overwrites; only mkdir fails when the target exists."""
    lock_line = next(line for line in script_text.splitlines()
                     if "mkdir" in line and "lock" in line)
    assert "2>nul" in lock_line, (
        "without 2>nul the mkdir failure prints to the console instead of "
        "being handled"
    )
    assert "echo" not in lock_line


def test_the_lock_is_released_so_the_next_update_is_not_blocked(script_text):
    assert "rmdir" in script_text
    assert script_text.index("rmdir") > script_text.index("robocopy"), (
        "the lock must outlive the copy"
    )


def test_releasing_the_lock_cannot_fail_the_mover(script_text):
    """A stale lock costs one skipped update; a failed mover costs trust."""
    rmdir_line = next(line for line in script_text.splitlines()
                      if "rmdir" in line)
    assert "2>nul" in rmdir_line


def test_the_wait_loop_still_waits_for_the_bridge_to_exit(script_text):
    """Reverse sabotage: the mutex must not skip the part that matters.

    Copying over a running bridge on Windows fails on locked files, which
    is why the wait loop exists in the first place (v4.60.16).
    """
    assert ":wait" in script_text
    assert "tasklist" in script_text
    assert script_text.index(":wait") < script_text.index("robocopy")
