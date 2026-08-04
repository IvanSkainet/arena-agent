"""A timed-out command must die whole, and die on time.

``arena/exec/handlers.py`` sat at 11.3% coverage -- the lowest of any code
that can act on the machine -- so the exec path was probed against a live
bridge instead of being read. The policy gates all held (auth, blocklist,
cautious allowlist, cwd confinement, output cap, malformed JSON). The
lifecycle did not.

``proc.kill()`` signals the shell only. For the ordinary shape of a command,
``bash -c "<something>"``, the actual work is a grandchild, and it survived:

* **A leaked process.** ``bash -c "sleep 300"`` with ``timeout=2`` left
  ``sleep 300`` running with PPID 1, outliving by minutes the request that
  created it. On a user's machine that is a process they never started and
  cannot see.
* **A timeout that was not the timeout.** The surviving grandchild inherits
  the stdout pipe, so ``communicate()`` could not finish and the 5s drain
  always ran to full length. Measured overshoot was a flat 5s:
  ``timeout=1`` took 6.0s, ``timeout=2`` took 8.0s, ``timeout=5`` took 10.0s.
  A caller asking for a one-second budget got six.

Both are one cause: the child was not started in its own process group, so
there was no group to kill. Fixed for the buffered and streaming paths
together, since they are separate code with the same bug.

These tests drive the runner directly rather than through HTTP so they are
fast and hermetic, and they assert timing and process survival -- the two
things that were actually wrong -- rather than which syscall was used.
"""
from __future__ import annotations

import asyncio
import os
import signal
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from arena.exec import runner as R  # noqa: E402

pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="POSIX process groups; the Windows path uses CREATE_NEW_PROCESS_GROUP",
)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


async def _run(cmd: str, timeout: int, tmp_path: Path):
    return await R.run_shell_command(
        request_id=f"t-{time.time()}",
        cmd=cmd,
        cwd=tmp_path,
        env=dict(os.environ),
        timeout=timeout,
        max_output=100_000,
        decode_output_fn=lambda b: b.decode("utf-8", "replace"),
    )


@pytest.mark.parametrize("timeout", [1, 2])
def test_timeout_returns_close_to_the_deadline(tmp_path, timeout):
    """The budget the caller asked for is the budget they get."""
    t0 = time.monotonic()
    result = asyncio.run(_run('bash -c "sleep 60"', timeout, tmp_path))
    elapsed = time.monotonic() - t0

    assert result["timed_out"] is True
    # Before the fix this was timeout + 5s, every time.
    assert elapsed < timeout + 2.5, (
        f"asked for {timeout}s, took {elapsed:.1f}s -- the killed shell's "
        "grandchild is still holding the output pipe open")


def _grandchild_pid_after_timeout(tmp_path, marker: str, nested: bool) -> int:
    """Time out a shell whose grandchild is a python sleeper; return its pid.

    The pid is reported by the grandchild itself into a file, rather than
    read from /proc: /proc does not exist on macOS, and an earlier version of
    this test asserted that Linux detail and reddened the whole macOS matrix
    while the code under test was fine. Assert the portable property, not the
    local mechanism for observing it.

    The sleeper is a tiny script on disk, and its path travels in the
    environment. Inlining it as ``python -c "..."`` meant nesting quotes
    inside ``bash -c '...'`` inside another shell, and the quoting did not
    survive the trip -- the probe silently reported nothing.
    """
    pidfile = tmp_path / f"{marker}.pid"
    script = tmp_path / f"{marker}_sleeper.py"
    script.write_text(
        "import os, sys, time, pathlib\n"
        "pathlib.Path(os.environ['ARENA_TEST_PIDFILE']).write_text(str(os.getpid()))\n"
        "time.sleep(300)\n",
        encoding="utf-8",
    )
    inner = f"{sys.executable} {script}"
    cmd = f"bash -c '{inner}'" if not nested else f"bash -c 'bash -c \"{inner}\"'"

    env = dict(os.environ, ARENA_TEST_PIDFILE=str(pidfile))
    asyncio.run(R.run_shell_command(
        request_id=f"probe-{marker}", cmd=cmd, cwd=tmp_path, env=env,
        timeout=1, max_output=100_000,
        decode_output_fn=lambda b: b.decode("utf-8", "replace"),
    ))

    for _ in range(40):
        if pidfile.exists() and pidfile.read_text().strip():
            break
        time.sleep(0.05)
    raw = pidfile.read_text().strip() if pidfile.exists() else ""
    assert raw, "the grandchild never reported its pid; the probe is broken"
    return int(raw)


def _assert_dead(pid: int, why: str) -> None:
    try:
        assert not _alive(pid), why
    finally:
        if _alive(pid):
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass


def test_timeout_kills_the_grandchild_not_just_the_shell(tmp_path):
    """A leaked process outlives the request that created it."""
    pid = _grandchild_pid_after_timeout(tmp_path, "orphan", nested=False)
    time.sleep(0.5)
    _assert_dead(pid, f"pid {pid} survived the timeout and reparented to init; "
                      "killing the shell alone does not kill what it started")


def test_nested_shells_are_killed_too(tmp_path):
    """Depth is not a loophole -- the group covers the whole tree."""
    pid = _grandchild_pid_after_timeout(tmp_path, "nested", nested=True)
    time.sleep(0.5)
    _assert_dead(pid, "a nested shell escaped the process-group kill")


def test_the_child_really_is_in_its_own_group(tmp_path):
    """The mechanism, checked once, so the tests above cannot pass by luck."""
    async def _probe():
        proc = await asyncio.create_subprocess_shell(
            "echo $$", cwd=str(tmp_path), env=dict(os.environ),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            **R._process_group_kwargs(),
        )
        out, _ = await proc.communicate()
        return proc.pid, out
    pid, _out = asyncio.run(_probe())
    # A child in its own session has pgid == pid; sharing ours would mean the
    # group kill could take the bridge down with it.
    assert pid != os.getpgid(os.getpid()), "child shares the bridge's group"


def test_normal_commands_are_unaffected(tmp_path):
    """A fix that broke ordinary execution would be worse than the bug."""
    result = asyncio.run(_run("echo hello-from-exec", 10, tmp_path))
    assert result["timed_out"] is False
    assert result["exit_code"] == 0
    assert "hello-from-exec" in result["stdout"]


def test_kill_helper_survives_an_already_dead_process(tmp_path):
    """Cleanup must never raise on the racy path where the child just exited."""
    async def _probe():
        proc = await asyncio.create_subprocess_shell(
            "true", cwd=str(tmp_path), env=dict(os.environ),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            **R._process_group_kwargs(),
        )
        await proc.communicate()
        R._kill_process_tree(proc)   # must not raise
        R._kill_process_tree(proc)   # twice, for good measure
    asyncio.run(_probe())
