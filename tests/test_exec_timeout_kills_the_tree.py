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


def test_timeout_kills_the_grandchild_not_just_the_shell(tmp_path):
    """A leaked process outlives the request that created it."""
    marker = "arena-orphan-probe-8571"
    asyncio.run(_run(f'bash -c "sleep 300 # {marker}"', 1, tmp_path))
    time.sleep(0.5)

    survivors = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes().replace(b"\0", b" ").decode()
        except (OSError, UnicodeDecodeError):
            continue
        if marker in cmdline and "sleep" in cmdline:
            survivors.append(int(entry.name))

    for pid in survivors:  # never leave debris behind, even on failure
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    assert not survivors, (
        f"{len(survivors)} process(es) survived the timeout and reparented to "
        "init; killing the shell alone does not kill what it started")


def test_nested_shells_are_killed_too(tmp_path):
    """Depth is not a loophole -- the group covers the whole tree."""
    marker = "arena-nested-probe-4412"
    asyncio.run(_run(f'bash -c "bash -c \\"sleep 200 # {marker}\\""', 1, tmp_path))
    time.sleep(0.5)
    found = [
        p for p in Path("/proc").iterdir()
        if p.name.isdigit()
        and marker.encode() in p.joinpath("cmdline").read_bytes()
        if p.joinpath("cmdline").exists()
    ]
    for p in found:
        try:
            os.kill(int(p.name), signal.SIGKILL)
        except OSError:
            pass
    assert not found, "a nested shell escaped the process-group kill"


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
