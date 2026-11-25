"""v4.169.44: Windows exec timeout/cancellation must kill descendants.

The live incident was a timed-out `/v1/exec/script` request. The bridge killed
its `cmd.exe` shell, but `powershell.exe` survived for three hours and reached
44.5 GiB private bytes. `CREATE_NEW_PROCESS_GROUP` alone is not recursive on
Windows; `taskkill /T` is required.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from arena.exec import runner as R
from arena.tasks import ownership


class FakeProcess:
    def __init__(self, pid: int = 15300, *, returncode=None) -> None:
        self.pid = pid
        self.returncode = returncode
        self.kill_calls = 0
        self.wait_calls = 0
        self.stdout = None
        self.stderr = None

    def kill(self) -> None:
        self.kill_calls += 1
        self.returncode = -9

    async def wait(self) -> int:
        self.wait_calls += 1
        self.returncode = -9
        return -9


def test_windows_tree_kill_uses_taskkill_t_and_f(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = FakeProcess()
    calls: list[tuple[list[str], dict]] = []

    class Completed:
        returncode = 0

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return Completed()

    monkeypatch.setattr(R.sys, "platform", "win32")
    monkeypatch.setattr(R.subprocess, "run", fake_run)
    monkeypatch.setattr(R.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False)

    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    R._kill_process_tree(proc)

    assert calls[0][0] == [r"C:\Windows\System32\taskkill.exe", "/PID", "15300", "/T", "/F"]
    assert calls[0][1]["check"] is False
    assert calls[0][1]["timeout"] == 10
    assert calls[0][1]["creationflags"] == 0x08000000
    assert proc.kill_calls == 0


def test_windows_taskkill_failure_falls_back_to_direct_kill(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = FakeProcess()

    class Failed:
        returncode = 128

    monkeypatch.setattr(R.sys, "platform", "win32")
    monkeypatch.setattr(R.subprocess, "run", lambda *_a, **_k: Failed())

    R._kill_process_tree(proc)
    assert proc.kill_calls == 1


def test_cancellation_cleanup_kills_and_reaps_a_running_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = FakeProcess()
    killed: list[int] = []
    monkeypatch.setattr(R, "_kill_process_tree", lambda child: killed.append(child.pid))

    asyncio.run(R._terminate_if_running(proc))

    assert killed == [15300]
    assert proc.wait_calls == 1


def test_cancellation_cleanup_is_noop_after_normal_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = FakeProcess(returncode=0)
    monkeypatch.setattr(
        R,
        "_kill_process_tree",
        lambda _child: pytest.fail("completed process must not be killed"),
    )
    asyncio.run(R._terminate_if_running(proc))
    assert proc.wait_calls == 0


def test_buffered_runner_cancellation_cleans_the_os_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = asyncio.Event()

    class HangingProcess(FakeProcess):
        async def communicate(self):
            started.set()
            await asyncio.Event().wait()

    proc = HangingProcess(pid=40123)
    killed: list[int] = []

    async def fake_create(*_args, **_kwargs):
        return proc

    monkeypatch.setattr(R.asyncio, "create_subprocess_shell", fake_create)
    monkeypatch.setattr(R, "_new_job", lambda: None)  # the fake child has no real pid to hold
    monkeypatch.setattr(R, "_kill_process_tree", lambda child: killed.append(child.pid))

    async def scenario() -> None:
        task = asyncio.create_task(
            R.run_shell_command(
                request_id="cancel-buffered",
                cmd="ignored",
                cwd=tmp_path,
                env=dict(os.environ),
                timeout=300,
                max_output=1000,
                decode_output_fn=lambda b: b.decode(),
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert killed == [40123]
    assert proc.wait_calls == 1
    assert "cancel-buffered" not in R.ACTIVE_PROCESSES


def test_stream_runner_close_cleans_the_os_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    proc = FakeProcess(pid=40124)
    killed: list[int] = []

    async def fake_create(*_args, **_kwargs):
        return proc

    monkeypatch.setattr(R.asyncio, "create_subprocess_shell", fake_create)
    monkeypatch.setattr(R, "_new_job", lambda: None)  # the fake child has no real pid to hold
    monkeypatch.setattr(R, "_kill_process_tree", lambda child: killed.append(child.pid))

    async def scenario() -> None:
        stream = R.run_shell_command_stream(
            request_id="cancel-stream",
            cmd="ignored",
            cwd=tmp_path,
            env=dict(os.environ),
            timeout=300,
            max_output=1000,
        )
        first = await anext(stream)
        assert first == {"type": "start", "pid": 40124}
        await getattr(stream, "aclose")()

    asyncio.run(scenario())
    assert killed == [40124]
    assert proc.wait_calls == 1
    assert "cancel-stream" not in R.ACTIVE_PROCESSES


def _gone_within(pid: int, seconds: float) -> bool:
    """Report whether the process terminated within the allowance."""
    # The question is "has it terminated", not "can it still be opened": a
    # terminated process stays openable for as long as anyone holds a handle
    # to it. The product's wait-state probe answers the first question.
    deadline = time.monotonic() + seconds
    while ownership._windows_pid_is_alive(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


@pytest.mark.skipif(sys.platform != "win32", reason="live Windows taskkill contract")
def test_live_windows_timeout_kills_nested_child(tmp_path: Path) -> None:
    # The request timeout is long enough for two interpreters to start on a
    # busy runner, and the test checks that they did. `taskkill /T` walks the
    # tree that exists when it runs; a child created while it runs is a
    # different question, and one this test must not answer by accident.
    timeout, margin = 10, 2
    pidfile = tmp_path / "child.pid"
    child = tmp_path / "child.py"
    parent = tmp_path / "parent.py"
    child.write_text(
        "import os, pathlib, sys, time\n"
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))\n"
        "time.sleep(300)\n",
        encoding="utf-8",
    )
    parent.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])\n"
        "time.sleep(300)\n",
        encoding="utf-8",
    )
    cmd = subprocess.list2cmdline([sys.executable, str(parent), str(child), str(pidfile)])

    async def scenario() -> tuple[dict, float | None]:
        # One clock in one process: when did the child's report appear?
        began = time.monotonic()

        async def reported() -> float:
            while not pidfile.is_file():
                await asyncio.sleep(0.05)
            return time.monotonic() - began

        watching = asyncio.ensure_future(reported())
        outcome = await R.run_shell_command(
            request_id="windows-live-tree",
            cmd=cmd,
            cwd=tmp_path,
            env=dict(os.environ),
            timeout=timeout,
            max_output=1000,
            decode_output_fn=lambda b: b.decode("utf-8", "replace"),
        )
        if not watching.done():
            watching.cancel()
            return outcome, None
        return outcome, watching.result()

    result, ready_after = asyncio.run(scenario())
    assert result["timed_out"] is True
    assert ready_after is not None, "nested child did not report its pid"
    child_pid = int(pidfile.read_text())
    try:
        assert ready_after < timeout - margin, (
            f"the nested child was ready {ready_after:.1f}s into a {timeout}s timeout; "
            "the tree was not in place before the kill, so this run shows nothing"
        )
        assert _gone_within(child_pid, 10), (
            f"nested Windows child {child_pid}, ready {ready_after:.1f}s into the "
            f"{timeout}s timeout, was still running 10s after the request timed out"
        )
    finally:
        if ownership._windows_pid_is_alive(child_pid):
            subprocess.run(
                ["taskkill.exe", "/PID", str(child_pid), "/T", "/F"],
                check=False,
                capture_output=True,
            )


def test_windows_tree_killer_never_resolves_from_cwd_or_relative_system_root(monkeypatch):
    monkeypatch.setenv("SystemRoot", r"D:\Windows")
    assert R._windows_taskkill() == r"D:\Windows\System32\taskkill.exe"
    monkeypatch.setenv("SystemRoot", "relative-directory")
    with pytest.raises(OSError, match="absolute"):
        R._windows_taskkill()
