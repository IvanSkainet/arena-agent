"""Windows liveness checks must never signal a process."""
import os
import subprocess
import sys

import pytest

from arena.tasks import queue


def test_windows_path_uses_query_not_os_kill(monkeypatch):
    # Avoid changing global os.name: pathlib and pytest also depend on it.
    class WindowsOS:
        name = "nt"

        def kill(self, *_args):
            raise AssertionError("os.kill on Windows can terminate the process")

    monkeypatch.setattr(queue, "os", WindowsOS())
    seen = []
    monkeypatch.setattr(queue, "_windows_pid_is_alive", lambda pid: seen.append(pid) or True)
    assert queue.pid_is_alive(42) is True
    assert seen == [42]


@pytest.mark.skipif(os.name != "nt", reason="native Windows process API")
def test_native_probe_preserves_live_child():
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        assert queue.pid_is_alive(child.pid) is True
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=10)
    assert queue.pid_is_alive(child.pid) is False


def test_signalled_process_is_dead_even_when_exit_code_would_be_still_active(monkeypatch):
    import ctypes

    from arena.tasks.ownership import _windows_pid_is_alive

    class Function:
        def __init__(self, implementation):
            self.implementation = implementation

        def __call__(self, *args):
            return self.implementation(*args)

    closed = []

    class Kernel:
        OpenProcess = Function(lambda *_args: 123)
        WaitForSingleObject = Function(lambda *_args: 0)
        CloseHandle = Function(lambda handle: closed.append(handle) or 1)

        def GetExitCodeProcess(self, *_args):
            raise AssertionError("Exit code 259 is not a reliable liveness signal")

    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: Kernel(), raising=False)
    assert _windows_pid_is_alive(42) is False
    assert closed == [123]


@pytest.mark.skipif(os.name != "nt", reason="native Windows process API")
def test_native_exit_259_is_not_mistaken_for_live_process():
    child = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(259)"])
    try:
        assert child.wait(timeout=10) == 259
        assert queue.pid_is_alive(child.pid) is False
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=10)
