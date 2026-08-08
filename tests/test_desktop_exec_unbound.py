"""A timeout handler must not crash on a process that was never started.

Found by Pyright, via Serena, across the whole tree:

    arena/desktop/exec.py  [reportPossiblyUnboundVariable]  "proc" is
    possibly unbound

It had been saying that on every run. The first sweep reported the
codebase clean because the result parser was wrong (v4.169.5); once it
was fixed, this was one of 98 real findings.

The failure is narrow but ugly. `create_subprocess_shell` can raise --
a missing shell (OSError), a restricted profile (PermissionError), some
Windows event-loop policies (NotImplementedError) -- or, as reproduced
below, time out during the spawn itself. The `except asyncio.TimeoutError`
branch then ran `proc.kill()` on a name that was never bound, so the
caller got an `UnboundLocalError` raised from inside an exception
handler instead of the tidy "command timed out" dict the function
promises.

Verified against the pre-fix code: `UnboundLocalError: cannot access
local variable 'proc'`.
"""
from __future__ import annotations

import asyncio
from unittest import mock

import pytest

from arena.desktop.exec import _desktop_exec


def test_a_normal_command_still_works():
    result = asyncio.run(_desktop_exec("echo hi", timeout=10))
    assert result["ok"] is True
    assert "hi" in result["stdout"]


def test_a_real_timeout_returns_the_error_dict():
    result = asyncio.run(_desktop_exec("sleep 5", timeout=0.3))
    assert result["ok"] is False
    assert "timed out" in result["error"]


def test_a_timeout_during_spawn_does_not_raise_unbound_local():
    """The exact defect. Pre-fix this raised UnboundLocalError."""
    async def never_starts(*_args, **_kwargs):
        raise asyncio.TimeoutError()

    with mock.patch("asyncio.create_subprocess_shell", never_starts):
        result = asyncio.run(_desktop_exec("anything", timeout=1))

    assert result["ok"] is False
    assert "timed out" in result["error"], (
        "the timeout branch did not produce its error dict -- it most "
        "likely crashed on an unbound `proc`")


@pytest.mark.parametrize("failure", [
    OSError("no shell"),
    PermissionError("blocked by profile"),
    NotImplementedError("event loop does not support subprocesses"),
])
def test_a_failed_spawn_is_reported_not_raised(failure):
    """Every way the spawn can fail must come back as a dict.

    These are the realistic causes on the platforms this bridge runs on:
    a stripped container, a locked-down Windows profile, and the
    Proactor/Selector event-loop split.
    """
    async def explodes(*_args, **_kwargs):
        raise failure

    with mock.patch("asyncio.create_subprocess_shell", explodes):
        result = asyncio.run(_desktop_exec("anything", timeout=1))

    assert result["ok"] is False
    assert result["error"]


def test_a_timed_out_process_is_reaped_not_just_killed():
    """`kill()` without `wait()` leaves a zombie.

    asyncio then logs "Task was destroyed but it is pending" at some
    unrelated later moment, which is the kind of noise that sends
    someone debugging the wrong subsystem.
    """
    killed = {"kill": False, "wait": False}

    class FakeProc:
        returncode = None

        async def communicate(self):
            await asyncio.sleep(10)

        def kill(self):
            killed["kill"] = True

        async def wait(self):
            killed["wait"] = True
            return -9

    async def spawn(*_args, **_kwargs):
        return FakeProc()

    with mock.patch("asyncio.create_subprocess_shell", spawn):
        result = asyncio.run(_desktop_exec("sleep", timeout=0.2))

    assert result["ok"] is False
    assert killed["kill"] is True, "the timed-out process was not killed"
    assert killed["wait"] is True, (
        "the killed process was never awaited -- it stays a zombie")


def test_a_process_that_dies_between_timeout_and_kill_is_tolerated():
    """The race: it exits on its own microseconds after the timeout.

    `kill()` then raises ProcessLookupError, and turning that into a
    crash would replace a clean timeout report with a traceback.
    """
    class VanishedProc:
        returncode = None

        async def communicate(self):
            await asyncio.sleep(10)

        def kill(self):
            raise ProcessLookupError()

        async def wait(self):
            return -9

    async def spawn(*_args, **_kwargs):
        return VanishedProc()

    with mock.patch("asyncio.create_subprocess_shell", spawn):
        result = asyncio.run(_desktop_exec("sleep", timeout=0.2))

    assert result["ok"] is False
    assert "timed out" in result["error"]
