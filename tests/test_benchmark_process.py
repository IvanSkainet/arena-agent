"""T74: Linux process ownership and interruption cleanup."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from arena.governance import benchmark_runner as bench


@pytest.mark.skipif(sys.platform != "linux", reason="Linux waitid polling contract")
@pytest.mark.parametrize("timeout", [None, 1])
def test_wait_observation_respects_exact_deadline_and_poll_interval(monkeypatch, timeout):
    ticks = iter([10.0, 11.0])
    observations = iter([None, object()])
    sleeps = []
    monkeypatch.setattr(bench.os, "waitid", lambda *args: next(observations))
    monkeypatch.setattr(bench, "time", SimpleNamespace(monotonic=lambda: next(ticks), sleep=sleeps.append))
    if timeout is None:
        bench.wait_unreaped(12345, timeout)
        assert sleeps == [0.02]
    else:
        with pytest.raises(subprocess.TimeoutExpired) as caught:
            bench.wait_unreaped(12345, timeout)
        assert caught.value.timeout == 1
        assert caught.value.cmd == "12345"
        assert sleeps == []



@pytest.mark.skipif(sys.platform != "linux", reason="Linux process-group cleanup contract")
@pytest.mark.parametrize("interrupted", [False, True])
def test_owned_process_group_is_cleaned_up(monkeypatch, tmp_path, interrupted):
    calls = []

    class Process:
        pid = 12345

        def wait(self):
            calls.append(("reap", self.pid))
            return 0

    def observe(pid, timeout):
        calls.append(("observe", timeout))
        if interrupted and timeout == 10:
            raise subprocess.TimeoutExpired("fixture", 10)

    def popen(argv, **kwargs):
        assert kwargs["start_new_session"] is True
        return Process()

    monkeypatch.setattr(bench.subprocess, "Popen", popen)
    monkeypatch.setattr(bench, "wait_unreaped", observe)
    monkeypatch.setattr(bench.os, "waitid", lambda *a: calls.append(("ownership", a[1])))
    monkeypatch.setattr(bench.os, "killpg", lambda pid, sig: calls.append((pid, sig)))
    if interrupted:
        with pytest.raises(subprocess.TimeoutExpired):
            bench.execute(["fixture"], root=tmp_path, env={}, log=None, timeout=10)
    else:
        assert bench.execute(["fixture"], root=tmp_path, env={}, log=None, timeout=10) == 0
    assert calls == [("observe", 10), ("ownership", 12345),
                     (12345, bench.signal.SIGTERM), ("observe", 5),
                     (12345, bench.signal.SIGKILL), ("reap", 12345)]



@pytest.mark.skipif(sys.platform != "linux", reason="Linux process-group cleanup contract")
def test_execute_real_successful_child(tmp_path):
    with (tmp_path / "child.log").open("w") as log:
        assert bench.execute([sys.executable, "-c", 'print("fixture complete")'],
                             root=tmp_path, env={}, log=log, timeout=10) == 0
    assert (tmp_path / "child.log").read_text().strip() == "fixture complete"



@pytest.mark.skipif(sys.platform != "linux", reason="Linux waitid ownership contract")
def test_group_is_never_signalled_after_ownership_was_lost(monkeypatch, tmp_path):
    def lost(*args):
        raise ChildProcessError("already reaped")

    monkeypatch.setattr(bench.os, "waitid", lost)
    monkeypatch.setattr(bench.os, "killpg", lambda *a: pytest.fail("signalled an unowned group"))
    with pytest.raises(ChildProcessError):
        bench.cleanup_owned_process(SimpleNamespace(pid=12345))



@pytest.mark.skipif(sys.platform != "linux", reason="Linux waitid ownership contract")
def test_real_group_leader_stays_unreaped_until_last_signal(monkeypatch, tmp_path):
    real_killpg = bench.os.killpg
    observed = []

    def killpg(pid, sig):
        # ECHILD here would mean the PID could have been recycled.
        bench.os.waitid(bench.os.P_PID, pid, bench.os.WEXITED | bench.os.WNOHANG | bench.os.WNOWAIT)
        observed.append((pid, sig))
        real_killpg(pid, sig)

    monkeypatch.setattr(bench.os, "killpg", killpg)
    with (tmp_path / "child.log").open("w") as log:
        assert bench.execute([sys.executable, "-c", "pass"], root=tmp_path, env={}, log=log, timeout=10) == 0
    assert [sig for _, sig in observed] == [bench.signal.SIGTERM, bench.signal.SIGKILL]
    with pytest.raises(ChildProcessError):
        bench.os.waitid(bench.os.P_PID, observed[0][0], bench.os.WEXITED | bench.os.WNOHANG | bench.os.WNOWAIT)



@pytest.mark.skipif(sys.platform != "linux", reason="Linux owned interruption contract")
def test_interrupt_also_signals_before_reaping(monkeypatch, tmp_path):
    calls = []

    def observe(pid, timeout):
        if timeout == 10:
            raise KeyboardInterrupt

    def reap():
        calls.append("reap")
        return -15

    monkeypatch.setattr(bench.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(pid=12345, wait=reap))
    monkeypatch.setattr(bench, "wait_unreaped", observe)
    monkeypatch.setattr(bench.os, "waitid", lambda *a: None)
    monkeypatch.setattr(bench.os, "killpg", lambda pid, sig: calls.append(sig))
    with pytest.raises(KeyboardInterrupt):
        bench.execute(["fixture"], root=tmp_path, env={}, log=None, timeout=10)
    assert calls == [bench.signal.SIGTERM, bench.signal.SIGKILL, "reap"]



@pytest.mark.skipif(sys.platform != "linux", reason="Linux process group contract")
@pytest.mark.parametrize("timed_out", [False, True])
def test_real_descendant_cannot_outlive_owned_execution(tmp_path, timed_out):
    import time

    marker = tmp_path / "descendant.pid"
    child = "import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)"
    script = (
        "import subprocess,sys,time,pathlib; "
        f"p=subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"pathlib.Path({str(marker)!r}).write_text(str(p.pid)); "
        + ("time.sleep(60)" if timed_out else "time.sleep(0.2)")
    )
    with (tmp_path / "execution.log").open("w") as log:
        if timed_out:
            with pytest.raises(subprocess.TimeoutExpired):
                bench.execute([sys.executable, "-c", script], root=tmp_path, env={}, log=log, timeout=1)
        else:
            assert bench.execute([sys.executable, "-c", script], root=tmp_path, env={}, log=log, timeout=10) == 0
    pid = int(marker.read_text())
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        try:
            state = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()[0]
        except FileNotFoundError:
            return
        if state == "Z":  # Dead orphan awaits the container init's reap.
            return
        time.sleep(0.02)
    pytest.fail("owned descendant remained alive after cleanup")



def _interrupt_when_ready(marker, stop, captured, signum):
    import os
    import time

    deadline = time.monotonic() + 10
    while not stop.wait(0.02):
        if time.monotonic() >= deadline:
            os.kill(os.getpid(), signum)  # Cancel even before the PID is known.
            return
        if marker.exists():
            # Child publishes atomically, after installing its TERM handler.
            captured.append(os.pidfd_open(int(marker.read_text())))
            os.kill(os.getpid(), signum)
            return


def _reap_test_owned_groups(processes):
    import os
    import signal

    for proc in processes:
        try:
            os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        except ChildProcessError:
            continue  # Already reaped: never signal a potentially reused PGID.
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux real cancellation contract")
@pytest.mark.parametrize("entry", ["execute-sigint", "preflight-sigterm"])
def test_real_sigint_cleans_owned_group(tmp_path, monkeypatch, entry):
    import os
    import select
    import signal
    import threading

    from scripts import preflight

    marker = tmp_path / "child.pid"
    child = (
        "import os,pathlib,signal,time; "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"ready=pathlib.Path({str(marker)!r}); pending=ready.with_suffix('.tmp'); "
        "pending.write_text(str(os.getpid())); pending.replace(ready); time.sleep(60)"
    )
    leader = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(60)"
    processes, captured = [], []
    original_popen = bench.subprocess.Popen

    def own(*args, **kwargs):
        proc = original_popen(*args, **kwargs)
        processes.append(proc)  # The test directly owns the unreaped leader.
        return proc

    monkeypatch.setattr(bench.subprocess, "Popen", own)
    signum = signal.SIGINT if entry == "execute-sigint" else signal.SIGTERM
    stop = threading.Event()
    sender = threading.Thread(target=_interrupt_when_ready, args=(marker, stop, captured, signum))
    previous = signal.signal(signal.SIGINT, signal.default_int_handler)
    sender.start()
    try:
        argv = [sys.executable, "-c", leader]
        with pytest.raises(KeyboardInterrupt):
            if entry == "execute-sigint":
                bench.execute(argv, root=tmp_path, env={}, log=None, timeout=15)
            else:
                preflight._execute_full(argv, {})
        assert captured, "child readiness never reached"
        assert select.select(captured, [], [], 3)[0], "descendant survived cancellation cleanup"
    finally:
        stop.set()
        sender.join(timeout=2)
        signal.signal(signal.SIGINT, previous)
        _reap_test_owned_groups(processes)
        for descriptor in captured:
            try:
                signal.pidfd_send_signal(descriptor, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.close(descriptor)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux repeated cancellation contract")
@pytest.mark.parametrize("initial_interruption", [False, True])
def test_second_sigint_is_deferred_until_kill_and_reap(monkeypatch, tmp_path, initial_interruption):
    import os
    import signal

    calls = []
    original = KeyboardInterrupt("first cancellation")

    def observe(pid, timeout):
        if timeout == 10:
            if initial_interruption:
                raise original
            return
        os.kill(os.getpid(), signal.SIGINT)
        calls.append("grace finished")

    def reap():
        calls.append("reap")
        return -9

    monkeypatch.setattr(bench.subprocess, "Popen", lambda *a, **kw: SimpleNamespace(pid=12345, wait=reap))
    monkeypatch.setattr(bench, "wait_unreaped", observe)
    monkeypatch.setattr(bench.os, "waitid", lambda *a: None)
    monkeypatch.setattr(bench.os, "killpg", lambda pid, sig: calls.append(sig))
    previous = signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        with pytest.raises(KeyboardInterrupt) as caught:
            bench.execute(["fixture"], root=tmp_path, env={}, log=None, timeout=10)
        if initial_interruption:
            assert caught.value is original
        assert calls == [signal.SIGTERM, "grace finished", signal.SIGKILL, "reap"]
        assert signal.getsignal(signal.SIGINT) == signal.default_int_handler
    finally:
        signal.signal(signal.SIGINT, previous)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux startup cancellation contract")
def test_startup_cancellation_cannot_lose_created_child(monkeypatch, tmp_path):
    import os
    import signal

    calls = []

    def reap():
        calls.append("reap")
        return -9

    def create(*args, **kwargs):
        os.kill(os.getpid(), signal.SIGINT)
        return SimpleNamespace(pid=12345, wait=reap)

    monkeypatch.setattr(bench.subprocess, "Popen", create)
    monkeypatch.setattr(bench, "wait_unreaped", lambda *a: None)
    monkeypatch.setattr(bench.os, "waitid", lambda *a: None)
    monkeypatch.setattr(bench.os, "killpg", lambda pid, sig: calls.append(sig))
    previous = signal.signal(signal.SIGINT, signal.default_int_handler)
    try:
        with pytest.raises(KeyboardInterrupt):
            bench.execute(["fixture"], root=tmp_path, env={}, log=None, timeout=10)
        assert calls == [signal.SIGTERM, signal.SIGKILL, "reap"]
    finally:
        signal.signal(signal.SIGINT, previous)


def test_missing_readiness_still_cancels_without_a_descendant_pid(tmp_path, monkeypatch):
    import os
    import time

    calls = []
    ticks = iter([0, 11])
    with monkeypatch.context() as patch:
        patch.setattr(time, "monotonic", lambda: next(ticks))
        patch.setattr(os, "kill", lambda pid, sig: calls.append((pid, sig)))
        _interrupt_when_ready(tmp_path / "absent.pid", SimpleNamespace(wait=lambda delay: False), [], 2)
    assert calls == [(os.getpid(), 2)]


@pytest.mark.skipif(sys.platform != "linux", reason="Linux descendant TERM grace")
def test_descendant_gets_grace_after_leader_exit(tmp_path):
    marker = tmp_path / "grace-completed"
    ready = tmp_path / "ready"
    child = (
        "import pathlib,signal,time; "
        f"marker=pathlib.Path({str(marker)!r}); "
        "signal.signal(signal.SIGTERM,lambda *a:(time.sleep(0.3),marker.write_text('done'),exit(0))); "
        f"pathlib.Path({str(ready)!r}).write_text('ready'); time.sleep(60)"
    )
    leader = (
        "import subprocess,sys,pathlib,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
        f"ready=pathlib.Path({str(ready)!r}); "
        "exec('while not ready.exists(): time.sleep(0.01)')"
    )
    with (tmp_path / "child.log").open("w") as log:
        assert bench.execute([sys.executable, "-c", leader], root=tmp_path, env={}, log=log, timeout=10) == 0
    assert marker.read_text() == "done"
