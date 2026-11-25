"""#516: a Windows command runs inside a Job Object and is killed through it."""
# ``taskkill /T`` kills the tree it finds when it looks. It misses a process
# created while it runs, and it finds nothing at all once the first process of
# the tree has exited. The second gap is not a race, so the live test for it
# fails every time without the job.
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from arena.exec import runner as R, win_job
from arena.tasks import ownership

SUSPENDED = 0x00000004


# `R.asyncio` is the process-wide asyncio; replacing a name on it would replace
# it for every test running beside this one.
class View:
    """The runner's own view of a module, with some names replaced."""

    def __init__(self, module: Any, **replaced: Any) -> None:
        """Replace the given names; everything else is the module's own."""
        self._module = module
        self.__dict__.update(replaced)

    def __getattr__(self, name: str) -> Any:
        """Fall through to the real module."""
        return getattr(self._module, name)


class FakeJob:
    """Records what the runner asks of a job; fails where a test tells it to."""

    def __init__(self, events: list[tuple], members: list, failing: tuple[str, ...] = ()) -> None:
        """Share the event log and the list of processes the job would kill."""
        self.events = events
        self.members = members
        self.failing = failing

    def _step(self, *event: Any) -> None:
        self.events.append(event)
        if event[0] in self.failing:
            raise OSError(f"{event[0]} failed")

    def hold(self, pid: int) -> None:
        self._step("hold", pid)

    def terminate(self) -> None:
        self._step("terminate")
        for member in self.members:
            member.returncode = -9 if member.returncode is None else member.returncode

    def disarm(self) -> None:
        self._step("disarm")

    def close(self) -> None:
        self._step("close")


class FakeProcess:
    """A child that exits by itself, or hangs until it is killed."""

    # No pipes unless a test gives it some.
    stdout: Any = None
    stderr: Any = None

    def __init__(self, events: list[tuple], *, hangs: bool = False, pid: int = 5160) -> None:
        """Share the event log; `hangs` keeps the child running until killed."""
        self.events = events
        self.pid = pid
        self.returncode: int | None = None
        self.hangs = hangs
        self.reading = asyncio.Event()
        self.reaping: asyncio.Event | None = None

    def kill(self) -> None:
        self.events.append(("kill",))
        self.returncode = -9

    async def wait(self) -> int:
        if self.reaping is not None:  # a test wants the exit wait to hang
            self.reaping.set()
            await asyncio.Event().wait()
        self.returncode = -9 if self.returncode is None else self.returncode
        return self.returncode

    async def communicate(self) -> tuple[bytes, bytes]:
        self.reading.set()
        if self.hangs and self.returncode is None:
            await asyncio.Event().wait()
        self.returncode = 0 if self.returncode is None else self.returncode
        return b"out", b""


def _harness(monkeypatch: pytest.MonkeyPatch, *, failing: tuple[str, ...] = (), **process: Any):
    """Replace the job and the spawn; return the shared event log and the process."""
    events: list[tuple] = []
    made: list[FakeProcess] = []

    def new_job() -> FakeJob:
        events.append(("create",))
        return FakeJob(events, made, failing)

    async def spawn(*_args: Any, **kwargs: Any) -> FakeProcess:
        events.append(("spawn", bool(kwargs.get("creationflags", 0) & SUSPENDED)))
        made.append(FakeProcess(events, **process))
        return made[0]

    def no_taskkill(*_args: Any, **_kwargs: Any) -> None:
        events.append(("taskkill",))
        raise OSError("not used for a command that has a job")

    monkeypatch.setattr(R, "_new_job", new_job)
    monkeypatch.setattr(R, "asyncio", View(asyncio, create_subprocess_shell=spawn))
    monkeypatch.setattr(R, "subprocess", View(R.subprocess, run=no_taskkill))
    return events, made


def _buffered(tmp_path: Path, request_id: str, timeout: int = 300):
    return R.run_shell_command(
        request_id=request_id, cmd="ignored", cwd=tmp_path, env=dict(os.environ),
        timeout=timeout, max_output=1000, decode_output_fn=lambda b: b.decode("utf-8", "replace"))


def _stream(tmp_path: Path, request_id: str, timeout: int = 300):
    return R.run_shell_command_stream(
        request_id=request_id, cmd="ignored", cwd=tmp_path, env=dict(os.environ),
        timeout=timeout, max_output=1000)


def _nothing_left(request_id: str) -> None:
    assert request_id not in R.ACTIVE_PROCESSES
    assert len(R._JOBS) == 0


def test_the_process_is_held_by_the_job_before_it_runs(tmp_path, monkeypatch) -> None:
    events, _made = _harness(monkeypatch)
    result = asyncio.run(_buffered(tmp_path, "held"))
    assert result["ok"] is True
    # Created suspended, held, and only then anything else.
    assert events[:3] == [("create",), ("spawn", True), ("hold", 5160)]


def test_a_command_that_completed_leaves_its_job_disarmed(tmp_path, monkeypatch) -> None:
    events, _made = _harness(monkeypatch)
    asyncio.run(_buffered(tmp_path, "completed"))
    assert events[3:] == [("disarm",), ("close",)]
    _nothing_left("completed")


def test_a_timed_out_command_is_killed_through_its_job(tmp_path, monkeypatch) -> None:
    events, _made = _harness(monkeypatch, hangs=True)
    result = asyncio.run(_buffered(tmp_path, "timed-out", timeout=1))
    assert result["timed_out"] is True
    assert events[3:] == [("terminate",), ("terminate",), ("close",)]
    assert ("disarm",) not in events and ("taskkill",) not in events
    _nothing_left("timed-out")


def test_a_cancelled_command_is_killed_through_its_job(tmp_path, monkeypatch) -> None:
    events, made = _harness(monkeypatch, hangs=True)

    async def scenario() -> None:
        task = asyncio.create_task(_buffered(tmp_path, "cancelled"))
        while not made:
            await asyncio.sleep(0)
        await made[0].reading.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert events[3:] == [("terminate",), ("terminate",), ("close",)]
    _nothing_left("cancelled")


def test_a_second_cancellation_during_cleanup_still_releases_the_job(tmp_path, monkeypatch) -> None:
    events, made = _harness(monkeypatch, hangs=True)

    async def scenario() -> None:
        task = asyncio.create_task(_buffered(tmp_path, "cancelled-twice"))
        while not made:
            await asyncio.sleep(0)
        await made[0].reading.wait()
        made[0].reaping = asyncio.Event()
        task.cancel()
        await made[0].reaping.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert events[-1] == ("close",)
    _nothing_left("cancelled-twice")


def test_cancellation_after_the_first_process_exited_still_kills_the_rest(tmp_path, monkeypatch) -> None:
    # The shell has exited; something it started still holds the output pipes.
    events, made = _harness(monkeypatch, hangs=True)

    async def scenario() -> None:
        task = asyncio.create_task(_buffered(tmp_path, "leader-gone"))
        while not made:
            await asyncio.sleep(0)
        await made[0].reading.wait()
        made[0].returncode = 0
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert events[3:] == [("terminate",), ("close",)]
    _nothing_left("leader-gone")


def test_a_stream_closed_early_is_killed_through_its_job(tmp_path, monkeypatch) -> None:
    events, _made = _harness(monkeypatch, hangs=True)

    async def scenario() -> None:
        stream = _stream(tmp_path, "stream-closed")
        assert await anext(stream) == {"type": "start", "pid": 5160}
        await getattr(stream, "aclose")()

    asyncio.run(scenario())
    assert events[3:] == [("terminate",), ("terminate",), ("close",)]
    _nothing_left("stream-closed")


def test_a_stream_that_completed_leaves_its_job_disarmed(tmp_path, monkeypatch) -> None:
    events, made = _harness(monkeypatch)

    async def scenario() -> list[dict]:
        stream = _stream(tmp_path, "stream-completed")
        seen = [await anext(stream)]
        for name, data in (("stdout", b"out"), ("stderr", b"")):
            reader = asyncio.StreamReader()
            reader.feed_data(data)
            reader.feed_eof()
            setattr(made[0], name, reader)
        made[0].returncode = 0
        seen.extend([event async for event in stream])
        return seen

    seen = asyncio.run(scenario())
    assert seen[-1]["type"] == "exit" and seen[-1]["timed_out"] is False
    assert events[3:] == [("disarm",), ("close",)]
    _nothing_left("stream-completed")


def test_a_stream_whose_output_could_not_be_read_is_not_completed(tmp_path, monkeypatch) -> None:
    events, made = _harness(monkeypatch)

    class BrokenPipe:
        async def read(self, _size: int) -> bytes:
            raise OSError("the pipe broke")

    async def scenario() -> list[dict]:
        stream = _stream(tmp_path, "stream-broken")
        seen = [await anext(stream)]
        reader = asyncio.StreamReader()
        reader.feed_eof()
        made[0].stdout, made[0].stderr = BrokenPipe(), reader
        made[0].returncode = 0
        seen.extend([event async for event in stream])
        return seen

    seen = asyncio.run(scenario())
    assert seen[-1]["type"] == "exit" and seen[-1]["timed_out"] is False
    # The shell exited by itself, but nobody knows what it wrote: nothing it
    # started is left running.
    assert events[3:] == [("terminate",), ("close",)]
    _nothing_left("stream-broken")


def test_a_command_that_cannot_be_held_is_not_run(tmp_path, monkeypatch) -> None:
    events, _made = _harness(monkeypatch, failing=("hold",))
    with pytest.raises(OSError, match="hold failed"):
        asyncio.run(_buffered(tmp_path, "not-held"))
    # The suspended process is killed and the job closed; nothing is resumed.
    assert events == [("create",), ("spawn", True), ("hold", 5160), ("kill",), ("close",)]
    _nothing_left("not-held")


def test_a_failed_spawn_closes_the_job(tmp_path, monkeypatch) -> None:
    events, _made = _harness(monkeypatch)

    async def refused(*_args: Any, **_kwargs: Any) -> None:
        events.append(("spawn",))
        raise FileNotFoundError("no such directory")

    monkeypatch.setattr(R, "asyncio", View(asyncio, create_subprocess_shell=refused))
    with pytest.raises(FileNotFoundError):
        asyncio.run(_buffered(tmp_path, "no-spawn"))
    assert events == [("create",), ("spawn",), ("close",)]
    _nothing_left("no-spawn")


def test_a_job_that_cannot_terminate_falls_back_to_the_tree_kill(tmp_path, monkeypatch) -> None:
    events, _made = _harness(monkeypatch, failing=("terminate",), hangs=True)
    monkeypatch.setattr(R, "sys", View(sys, platform="win32"))
    result = asyncio.run(_buffered(tmp_path, "fallback", timeout=1))
    assert result["timed_out"] is True
    # taskkill is tried, fails in this harness, and the direct kill follows.
    assert events[3:6] == [("terminate",), ("taskkill",), ("kill",)]
    assert events[-1] == ("close",)
    _nothing_left("fallback")


def test_a_job_that_cannot_be_disarmed_is_still_closed(tmp_path, monkeypatch) -> None:
    events, _made = _harness(monkeypatch, failing=("disarm",))
    assert asyncio.run(_buffered(tmp_path, "armed"))["ok"] is True
    assert events[3:] == [("disarm",), ("close",)]
    _nothing_left("armed")


@pytest.mark.skipif(sys.platform == "win32", reason="the process group does this work off Windows")
def test_there_is_no_job_off_windows(tmp_path) -> None:
    assert R._new_job() is None
    result = asyncio.run(R.run_shell_command(
        request_id="posix", cmd="echo plain", cwd=tmp_path, env=dict(os.environ),
        timeout=30, max_output=1000, decode_output_fn=lambda b: b.decode()))
    assert result["ok"] is True and result["stdout"].strip() == "plain"
    _nothing_left("posix")


def test_a_process_without_a_job_is_killed_the_old_way(monkeypatch) -> None:
    # arena/desktop/exec.py passes processes this module did not start.
    events: list[tuple] = []
    proc = FakeProcess(events)
    monkeypatch.setattr(R, "_kill_windows_tree", lambda pid: events.append(("taskkill", pid)) or True)
    monkeypatch.setattr(R, "sys", View(sys, platform="win32"))
    R._kill_process_tree(proc)
    assert events == [("taskkill", 5160)]


def test_a_process_that_cannot_be_registered_is_killed_the_old_way() -> None:
    class Slotted:
        __slots__ = ("kills",)

        def __init__(self) -> None:
            self.kills = 0

        def kill(self) -> None:
            self.kills += 1

    proc = Slotted()
    R._kill_process_tree(proc)
    R._release_job(proc, completed=False)
    assert proc.kills == 1


# ---------------------------------------------------------------------------
# Live Windows contract
# ---------------------------------------------------------------------------

live_windows = pytest.mark.skipif(sys.platform != "win32", reason="live Windows Job Object contract")

SLEEPER = (
    "import os, pathlib, sys, time\n"
    "pathlib.Path(sys.argv[1]).write_text(str(os.getpid()))\n"
    "time.sleep(int(sys.argv[2]))\n"
)

# The spawner stops by itself. The test must stay harmless on a build where
# the kill does not work, and light for the tests running beside it: two new
# processes a second, at most CHILDREN of them, each gone in half a minute.
CHILDREN = 30
SPAWNER = (
    "import os, pathlib, subprocess, sys, time\n"
    "seen = sys.argv[1]\n"
    "child = (\"import os, pathlib, sys, time; \"\n"
    "         \"pathlib.Path(sys.argv[1], str(os.getpid())).write_text(''); time.sleep(30)\")\n"
    f"for _ in range({CHILDREN}):\n"
    "    subprocess.Popen([sys.executable, '-c', child, seen])\n"
    "    time.sleep(0.5)\n"
    "time.sleep(30)\n"
)


def _alive(pid: int) -> bool:
    return ownership._windows_pid_is_alive(pid)


def _gone_within(pid: int, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while _alive(pid):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.1)
    return True


def _kill_leftovers(pids: list[int]) -> None:
    for pid in pids:
        if _alive(pid):
            R._kill_windows_tree(pid)


def _command(*argv: Any) -> str:
    """A command line for cmd.exe; the paths here hold no quotes."""
    return " ".join(f'"{part}"' for part in argv)


def _expect_killed(pidfile: Path, outlived: str) -> None:
    pid = int(pidfile.read_text())
    try:
        assert _gone_within(pid, 10), f"process {pid} outlived {outlived}"
    finally:
        _kill_leftovers([pid])


def _script(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


async def _appeared(path: Path, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while not path.is_file() or not path.read_text().strip():
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(0.05)
    return True


def _live(tmp_path: Path, request_id: str, cmd: str, timeout: int):
    return R.run_shell_command(
        request_id=request_id, cmd=cmd, cwd=tmp_path, env=dict(os.environ),
        timeout=timeout, max_output=10000, decode_output_fn=lambda b: b.decode("utf-8", "replace"))


# `start` hands the shell's output pipes to what it starts, so the command is
# not over until that program is. A program started without them leaves the
# command free to complete.
DETACH = (
    "import subprocess, sys\n"
    "quiet = subprocess.DEVNULL\n"
    "subprocess.Popen([sys.executable, *sys.argv[1:]], stdin=quiet, stdout=quiet, stderr=quiet)\n"
)


def _background(tmp_path: Path, pidfile: Path, seconds: int, *, keeps_pipes: bool) -> str:
    """A command whose shell exits at once and leaves a program running."""
    sleeper = (_script(tmp_path, "sleeper.py", SLEEPER), pidfile, seconds)
    if keeps_pipes:
        return 'start "" /b ' + _command(sys.executable, *sleeper)
    return _command(sys.executable, _script(tmp_path, "detach.py", DETACH), *sleeper)


@live_windows
def test_live_timeout_kills_what_the_shell_left_behind_after_exiting(tmp_path: Path) -> None:
    # The shell exits at once; the program it started keeps the output pipes,
    # so the request runs into its timeout. There is no tree left to walk.
    pidfile = tmp_path / "left.pid"

    async def scenario() -> tuple[dict, bool]:
        watching = asyncio.ensure_future(_appeared(pidfile, 30))
        outcome = await _live(tmp_path, "live-left-behind", _background(tmp_path, pidfile, 60, keeps_pipes=True), 6)
        return outcome, await watching

    result, reported = asyncio.run(scenario())
    assert reported, "the background program did not report its pid"
    _expect_killed(pidfile, "the request that timed out")
    assert result["timed_out"] is True
    _nothing_left("live-left-behind")


@live_windows
def test_live_timeout_stops_a_command_that_keeps_starting_processes(tmp_path: Path) -> None:
    seen = tmp_path / "seen"
    seen.mkdir()
    cmd = _command(sys.executable, _script(tmp_path, "spawner.py", SPAWNER), seen)

    def reported() -> list[int]:
        return sorted(int(entry.name) for entry in seen.iterdir())

    result = asyncio.run(_live(tmp_path, "live-spawner", cmd, 8))
    at_return = reported()
    try:
        assert result["timed_out"] is True
        assert 0 < len(at_return) < CHILDREN, (
            f"{len(at_return)} of {CHILDREN} children had started when the request timed out; "
            "the command was not in the middle of starting processes, so this run shows nothing")
        time.sleep(2)
        assert reported() == at_return, "processes kept appearing after the request timed out"
        survivors = [pid for pid in at_return if not _gone_within(pid, 10)]
        assert survivors == [], f"{len(survivors)} of {len(at_return)} children outlived the request"
    finally:
        time.sleep(1)
        _kill_leftovers(reported())
    _nothing_left("live-spawner")


@live_windows
def test_live_completed_command_leaves_its_background_program_running(tmp_path: Path) -> None:
    # The program does not hold the output pipes, so the command completes.
    pidfile = tmp_path / "kept.pid"

    async def scenario() -> tuple[dict, bool]:
        outcome = await _live(tmp_path, "live-kept", _background(tmp_path, pidfile, 30, keeps_pipes=False), 30)
        return outcome, await _appeared(pidfile, 30)

    result, reported = asyncio.run(scenario())
    assert result["timed_out"] is False and result["exit_code"] == 0
    assert reported, "the background program did not report its pid"
    pid = int(pidfile.read_text())
    try:
        time.sleep(1)
        assert _alive(pid), "a completed command's background program was killed"
    finally:
        _kill_leftovers([pid])
    _nothing_left("live-kept")


@live_windows
def test_live_cancellation_kills_the_whole_command(tmp_path: Path) -> None:
    pidfile = tmp_path / "nested.pid"
    parent = _script(tmp_path, "parent.py", (
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2], '60'])\n"
        "time.sleep(60)\n"))
    cmd = _command(sys.executable, parent, _script(tmp_path, "sleeper.py", SLEEPER), pidfile)

    async def scenario() -> bool:
        task = asyncio.create_task(_live(tmp_path, "live-cancel", cmd, 120))
        ready = await _appeared(pidfile, 30)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return ready

    assert asyncio.run(scenario()), "the nested child did not report its pid"
    _expect_killed(pidfile, "the cancelled request")
    _nothing_left("live-cancel")


@live_windows
def test_live_closed_stream_kills_what_the_shell_left_behind(tmp_path: Path) -> None:
    pidfile = tmp_path / "stream.pid"

    async def scenario() -> bool:
        stream = R.run_shell_command_stream(
            request_id="live-stream", cmd=_background(tmp_path, pidfile, 60, keeps_pipes=True),
            cwd=tmp_path, env=dict(os.environ), timeout=120, max_output=10000)
        assert (await anext(stream))["type"] == "start"
        ready = await _appeared(pidfile, 30)
        await getattr(stream, "aclose")()
        return ready

    assert asyncio.run(scenario()), "the background program did not report its pid"
    _expect_killed(pidfile, "the closed stream")
    _nothing_left("live-stream")


@live_windows
def test_live_command_that_cannot_be_held_leaves_no_suspended_process(tmp_path: Path, monkeypatch) -> None:
    started: list[int] = []
    real_spawn = asyncio.create_subprocess_shell

    class Unholdable(win_job.CommandJob):
        def hold(self, pid: int) -> None:
            raise OSError("cannot hold")

    async def spawn(*args: Any, **kwargs: Any):
        proc = await real_spawn(*args, **kwargs)
        started.append(proc.pid)
        return proc

    monkeypatch.setattr(R, "_new_job", Unholdable.create)
    monkeypatch.setattr(R, "asyncio", View(asyncio, create_subprocess_shell=spawn))
    marker = tmp_path / "ran.txt"
    with pytest.raises(OSError, match="cannot hold"):
        asyncio.run(_live(tmp_path, "live-unheld", f'echo ran> "{marker}"', 30))
    assert len(started) == 1
    assert _gone_within(started[0], 10), "the suspended shell was left behind"
    assert not marker.exists(), "the command ran although it could not be held"
    _nothing_left("live-unheld")


@live_windows
def test_live_job_refuses_to_be_used_after_close() -> None:
    job = win_job.CommandJob.create()
    job.close()
    job.close()  # closing twice is harmless
    for use in (job.terminate, job.disarm, lambda: job.hold(os.getpid())):
        with pytest.raises(OSError, match="closed"):
            use()


@live_windows
def test_live_job_reports_which_call_failed() -> None:
    job = win_job.CommandJob.create()
    try:
        with pytest.raises(OSError, match="OpenProcess"):
            job.hold(0)  # the idle process cannot be opened
    finally:
        job.close()
