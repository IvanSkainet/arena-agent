"""The bore monitor thread must not outlive the test that started it.

Split out of test_bore_parity_v4_169_35.py: these exercise the *teardown*
contract rather than bore's behaviour, and the parity file was long
enough that CodeScene flagged it.

Why the contract matters is #235. `daemon=True` only means "do not block
interpreter exit". A monitor thread from a finished test keeps running,
by which point monkeypatch has restored the stubs it captured -- so it
writes into whatever the next test installed. That produced a bore test
recording an argv of `[..., 'version']`: a concurrent runtime probe from
arena/workbench/runtimes.py.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import arena.admin.bore as bore_mod  # noqa: E402
from tests.test_bore_parity_v4_169_35 import _reset_bore_state  # noqa: E402,F401

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_the_teardown_check_reports_a_leaked_monitor(tmp_path):
    """Run a leaking test in a child pytest and require it to error.

    This is the test that actually exercises the fixture. Sabotage
    proved why it is needed: with only an inline probe, four separate
    mutations -- dropping the monitor handle, skipping the join,
    softening the assert, removing the state key -- all left the suite
    green, because nothing committed ever leaked a thread for the
    fixture to catch.

    A cleanup fixture that is never exercised is not a guarantee, it is
    a comment.
    """
    repo = Path(__file__).resolve().parents[1]
    leak = tmp_path / "test_leak.py"
    leak.write_text(
        "import sys, threading, time\n"
        f"sys.path.insert(0, {str(repo)!r})\n"
        "import arena.admin.bore as bore_mod\n"
        "from tests.test_bore_parity_v4_169_35 import _reset_bore_state  # noqa: F401\n"
        "\n"
        "class _NeverEnding:\n"
        "    def readline(self):\n"
        "        time.sleep(0.01)\n"
        "        return 'noise\\n'\n"
        "\n"
        "class _Proc:\n"
        "    def __init__(self):\n"
        "        self.stdout = _NeverEnding()\n"
        "    def poll(self):\n"
        "        return None\n"
        "\n"
        "def test_leaks(monkeypatch):\n"
        "    # Go through _start_bore so the production wiring is what\n"
        "    # records the handle. If bore stops recording it, the leak\n"
        "    # becomes invisible and this test fails.\n"
        "    monkeypatch.setattr(bore_mod, '_spawn', lambda *a, **k: _Proc())\n"
        "    monkeypatch.setattr(bore_mod, '_url_wait_seconds', lambda: 1.0)\n"
        "    bore_mod._start_bore('/bin/bore', 8765,\n"
        "                         subprocess_kwargs=lambda: {})\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(leak), "-p", "no:randomly",
         "-p", "no:cacheprovider", "--no-cov", "-q"],
        capture_output=True, text=True, timeout=300, cwd=str(repo),
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, (
        "a test that leaks a monitor thread was reported as clean:\n" + combined
    )
    assert "outlived its test" in combined, combined


def test_the_leak_detector_fires_on_a_thread_that_will_not_stop():
    """The teardown check must fail on a genuinely leaked thread.

    A cleanup fixture that cannot report a leak is worse than none: it
    reads as a guarantee while guaranteeing nothing. This drives
    _bore_monitor_thread with a stdout that never returns "" -- so the
    thread cannot exit -- and asserts that join() times out, which is
    the exact condition the fixture turns into a failure.

    Run inline rather than through pytest so the probe cannot leak into
    the wider session: the thread is stopped here before returning.
    """
    stop = threading.Event()

    class _NeverEndingStdout:
        def readline(self) -> str:
            if stop.is_set():
                return ""
            time.sleep(0.01)
            return "noise\n"

    class _FakeProc:
        def __init__(self) -> None:
            self.stdout = _NeverEndingStdout()

        def poll(self) -> None:
            return None

    thread = threading.Thread(
        target=bore_mod._bore_monitor_thread,
        args=(_FakeProc(), 8765),
        daemon=True,
    )
    thread.start()
    try:
        thread.join(timeout=0.2)
        assert thread.is_alive(), (
            "the probe thread exited on its own; it no longer models a leak"
        )
    finally:
        stop.set()
        thread.join(timeout=5)
    assert not thread.is_alive(), "probe thread failed to stop; would leak"
