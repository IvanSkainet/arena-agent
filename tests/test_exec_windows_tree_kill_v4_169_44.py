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

    R._kill_process_tree(proc)

    assert calls[0][0] == ["taskkill.exe", "/PID", "15300", "/T", "/F"]
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


def _windows_pid_alive(pid: int) -> bool:
    import ctypes
    from ctypes import wintypes

    query_limited_information = 0x1000
    kernel32 = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(query_limited_information, False, pid)
    if not handle:
        return False
    kernel32.CloseHandle(handle)
    return True


@pytest.mark.skipif(sys.platform != "win32", reason="live Windows taskkill contract")
def test_live_windows_timeout_kills_nested_child(tmp_path: Path) -> None:
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

    result = asyncio.run(
        R.run_shell_command(
            request_id="windows-live-tree",
            cmd=cmd,
            cwd=tmp_path,
            env=dict(os.environ),
            timeout=2,
            max_output=1000,
            decode_output_fn=lambda b: b.decode("utf-8", "replace"),
        )
    )
    assert result["timed_out"] is True
    assert pidfile.is_file(), "nested child did not report its pid"
    child_pid = int(pidfile.read_text())
    time.sleep(0.5)
    try:
        assert not _windows_pid_alive(child_pid), (
            f"nested Windows child {child_pid} survived request timeout"
        )
    finally:
        if _windows_pid_alive(child_pid):
            subprocess.run(
                ["taskkill.exe", "/PID", str(child_pid), "/T", "/F"],
                check=False,
                capture_output=True,
            )
