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
