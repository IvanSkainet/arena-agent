"""A subagent monitor that fails says so in the run directory and ends the run (#602)."""
# The detached monitor is started with stdout and stderr discarded. When it
# died, nothing recorded why, and the run stayed "spawned": `rm` and `prune`
# refuse an active run, so it could not even be cleaned up.
from __future__ import annotations

import json
import os
import runpy
import sys
from types import SimpleNamespace

import pytest

from arena import subagent_lifecycle as lifecycle

ERROR = "monitor failed: RuntimeError('the disk went away')"
# Contents of a state file that do not say whether the run is active.
_UNKNOWN = {
    "not-json": "{",
    "not-an-object": "[]",
    "too-deep": "[" * 200_000,
    "status-missing": "{}",
    "status-null": '{"status": null}',
    "status-number": '{"status": 0}',
    "status-true": '{"status": true}',
    "status-list": '{"status": []}',
}
_UNKNOWN_IDS, _UNKNOWN_STATES = list(_UNKNOWN), list(_UNKNOWN.values())


@pytest.fixture(name="run_dir")
def _run_dir(tmp_path):
    """Build a run directory the way `spawn` leaves it for a detached monitor."""
    directory = tmp_path / "subagents" / "0123456789"
    directory.mkdir(parents=True)
    _write(directory / "meta.json", {
        "id": "0123456789", "name": "probe", "cmd": "true", "timeout": 5,
        "wait": False, "status": "spawned", "cwd": str(tmp_path), "max_out": 10,
    })
    _write(directory / "summary.json", {"id": "0123456789", "name": "probe", "status": "spawned", "exit": None})
    return directory


@pytest.fixture(name="cli")
def _cli(run_dir, tmp_path, monkeypatch):
    """The subagent CLI looking at the directory that holds `run_dir`."""
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))  # Importing the CLI creates its home.
    from arena import subagent_cli

    monkeypatch.setattr(subagent_cli, "SUB_DIR", run_dir.parent)
    return subagent_cli


@pytest.fixture(name="failing_run")
def _failing_run(monkeypatch):
    """Make the supervised run raise, as a monitor whose last write is refused does."""
    def run(_directory, _workers):
        raise RuntimeError("the disk went away")

    monkeypatch.setattr(lifecycle, "run", run)


def _write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.usefixtures("failing_run")
def test_a_monitor_that_fails_leaves_its_traceback_and_ends_the_run_as_failed(run_dir):
    before = _read(run_dir / "meta.json")

    with pytest.raises(RuntimeError, match="the disk went away"):
        lifecycle.supervise(run_dir)

    log = (run_dir / lifecycle.MONITOR_LOG).read_text(encoding="utf-8")
    assert log.startswith("Traceback (most recent call last):")
    assert log.rstrip().endswith("RuntimeError: the disk went away")
    assert _read(run_dir / "meta.json") == {**before, "status": "fail", "error": ERROR}
    assert _read(run_dir / "summary.json") == {
        "id": "0123456789", "name": "probe", "status": "fail", "exit": None, "error": ERROR}


@pytest.mark.usefixtures("failing_run")
def test_meta_is_ended_last_so_a_run_never_reads_as_ended_before_its_summary_says_why(run_dir, monkeypatch):
    publish, written = lifecycle.write_private_json, []

    def write(path, value):
        written.append(path.name)
        return publish(path, value)

    monkeypatch.setattr(lifecycle, "write_private_json", write)

    with pytest.raises(RuntimeError):
        lifecycle.supervise(run_dir)

    assert written == ["summary.json", "meta.json"]


def test_a_refused_last_write_keeps_the_result_in_the_summary_and_ends_the_run(run_dir, monkeypatch):
    """The #581 case: the command finished, and the final `meta.json` write was refused."""
    publish, refused = lifecycle.write_private_json, []

    def write(path, value):
        if path.name == "meta.json" and not refused:
            refused.append(path)
            raise PermissionError(13, "held open")
        return publish(path, value)

    monkeypatch.setattr(lifecycle, "write_private_json", write)
    monkeypatch.setenv("ARENA_AGENT_HOME", str(run_dir.parent.parent))
    _write(run_dir / "meta.json", {**_read(run_dir / "meta.json"), "cmd": f'"{sys.executable}" -c pass'})

    with pytest.raises(PermissionError, match="held open"):
        lifecycle.supervise(run_dir)

    summary, meta = _read(run_dir / "summary.json"), _read(run_dir / "meta.json")
    assert (summary["status"], summary["exit"], summary.get("error")) == ("ok", 0, None)
    assert (meta["status"], meta["error"]) == ("fail", "monitor failed: PermissionError(13, 'held open')")
    assert "could not be updated" not in (run_dir / lifecycle.MONITOR_LOG).read_text(encoding="utf-8")


class _Worker:
    """Stand in for the worker process: it exits when asked to, or never."""

    stdin = None
    pid = 0

    def __init__(self, exits):
        self.exits, self.waits, self.killed = exits, 0, False

    def wait(self, timeout=None):
        self.waits += 1
        if self.waits > 1 and not self.exits:
            raise lifecycle.subprocess.TimeoutExpired("worker", timeout)
        return 0

    def poll(self):
        return 0 if self.exits and self.waits > 1 else None

    def kill(self):
        self.killed = True


@pytest.fixture(name="worker")
def _worker(request, monkeypatch):
    """Let `run()` start a stand-in worker; only this module's view of `subprocess` changes."""
    stand_in, real = _Worker(exits=request.param), lifecycle.subprocess
    monkeypatch.setattr(lifecycle, "subprocess", SimpleNamespace(
        Popen=lambda *_args, **_kwargs: stand_in, PIPE=real.PIPE, TimeoutExpired=real.TimeoutExpired))
    return stand_in


@pytest.mark.parametrize("worker", [False], indirect=True)
def test_a_worker_that_does_not_exit_leaves_the_run_active_and_says_so(run_dir, cli, worker, capsys):
    before = [_read(run_dir / name) for name in ("meta.json", "summary.json")]

    with pytest.raises(lifecycle.subprocess.TimeoutExpired):
        lifecycle.supervise(run_dir)

    after = [_read(run_dir / name) for name in ("meta.json", "summary.json")]
    assert worker.killed
    assert after == before
    log = (run_dir / lifecycle.MONITOR_LOG).read_text(encoding="utf-8")
    assert "TimeoutExpired" in log
    assert log.endswith("the worker did not exit; the run is left active\n")
    assert cli.rm_cmd(SimpleNamespace(id=run_dir.name)) == 1
    assert run_dir.exists()
    capsys.readouterr()


@pytest.mark.parametrize("worker", [True], indirect=True)
def test_a_failure_after_the_worker_has_exited_ends_the_run(run_dir, monkeypatch, worker):
    def refuse(path, _value):
        if path.name == "summary.json":
            raise PermissionError(13, "held open")

    publish = lifecycle.write_private_json
    monkeypatch.setattr(lifecycle, "write_private_json", lambda path, value: refuse(path, value) or publish(path, value))

    with pytest.raises(PermissionError, match="held open"):
        lifecycle.supervise(run_dir)

    assert worker.waits == 2
    assert _read(run_dir / "meta.json")["status"] == "fail"
    assert "the run is left active" not in (run_dir / lifecycle.MONITOR_LOG).read_text(encoding="utf-8")


@pytest.mark.usefixtures("failing_run")
def test_a_run_that_had_already_ended_keeps_what_was_recorded(run_dir):
    ended = {"id": "0123456789", "status": "timeout", "exit": 124}
    _write(run_dir / "meta.json", ended)
    _write(run_dir / "summary.json", ended)

    with pytest.raises(RuntimeError):
        lifecycle.supervise(run_dir)

    assert _read(run_dir / "meta.json") == ended
    assert _read(run_dir / "summary.json") == ended
    assert "RuntimeError: the disk went away" in (run_dir / lifecycle.MONITOR_LOG).read_text(encoding="utf-8")


@pytest.mark.usefixtures("failing_run")
@pytest.mark.parametrize("unreadable", _UNKNOWN_STATES, ids=_UNKNOWN_IDS)
def test_a_file_that_cannot_be_updated_is_named_in_the_log_and_the_first_failure_is_raised(run_dir, unreadable):
    (run_dir / "meta.json").write_text(unreadable, encoding="utf-8")

    with pytest.raises(RuntimeError, match="the disk went away"):
        lifecycle.supervise(run_dir)

    log = (run_dir / lifecycle.MONITOR_LOG).read_text(encoding="utf-8")
    assert "RuntimeError: the disk went away" in log
    assert "meta.json could not be updated: " in log
    assert "summary.json could not be updated" not in log
    assert (run_dir / "meta.json").read_text(encoding="utf-8") == unreadable
    assert _read(run_dir / "summary.json")["status"] == "fail"


@pytest.mark.usefixtures("failing_run")
def test_a_log_that_cannot_be_written_does_not_replace_the_first_failure(tmp_path):
    missing = tmp_path / "subagents" / "gone"

    with pytest.raises(RuntimeError, match="the disk went away"):
        lifecycle.supervise(missing)

    assert not missing.exists()


def test_a_monitor_that_succeeds_returns_the_summary_and_writes_no_error_log(run_dir, monkeypatch):
    monkeypatch.setattr(lifecycle, "run", lambda _directory, _workers: {"status": "ok"})

    assert lifecycle.supervise(run_dir) == {"status": "ok"}

    assert not (run_dir / lifecycle.MONITOR_LOG).exists()
    assert _read(run_dir / "meta.json")["status"] == "spawned"


def test_the_recorded_error_is_bounded(run_dir, monkeypatch):
    def run(_directory, _workers):
        raise RuntimeError("x" * 5000)

    monkeypatch.setattr(lifecycle, "run", run)

    with pytest.raises(RuntimeError):
        lifecycle.supervise(run_dir)

    error = _read(run_dir / "meta.json")["error"]
    assert len(error) == 500
    assert error.startswith("monitor failed: RuntimeError('xxx")


@pytest.mark.usefixtures("failing_run")
@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits; Windows uses deployment ACLs")
def test_the_error_log_is_private(run_dir):
    with pytest.raises(RuntimeError):
        lifecycle.supervise(run_dir)

    assert (run_dir / lifecycle.MONITOR_LOG).stat().st_mode & 0o777 == 0o600


@pytest.mark.filterwarnings("ignore:.*found in sys.modules:RuntimeWarning")  # runpy: already imported, on purpose
def test_the_detached_entry_point_is_supervised(run_dir, monkeypatch):
    meta = _read(run_dir / "meta.json")
    del meta["cmd"]
    _write(run_dir / "meta.json", meta)
    monkeypatch.setattr(sys, "argv", ["arena.subagent_lifecycle", str(run_dir)])

    with pytest.raises(KeyError, match="cmd"):
        runpy.run_module("arena.subagent_lifecycle", run_name="__main__")

    assert "KeyError: 'cmd'" in (run_dir / lifecycle.MONITOR_LOG).read_text(encoding="utf-8")
    assert _read(run_dir / "meta.json") == {**meta, "status": "fail", "error": "monitor failed: KeyError('cmd')"}


@pytest.mark.usefixtures("failing_run")
def test_a_waiting_spawn_whose_supervision_fails_does_not_leave_an_active_run(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ARENA_AGENT_HOME", str(tmp_path))
    from arena import subagent_cli as cli

    monkeypatch.setattr(cli, "ROOT", tmp_path)
    monkeypatch.setattr(cli, "SUB_DIR", tmp_path / "subagents")
    cli.SUB_DIR.mkdir(exist_ok=True)

    with pytest.raises(RuntimeError, match="the disk went away"):
        cli.spawn(SimpleNamespace(cmd="true", name="probe", timeout=5, wait=True, max_out=10))

    run = next(cli.SUB_DIR.iterdir())
    assert _read(run / "meta.json")["status"] == "fail"
    log = (run / lifecycle.MONITOR_LOG).read_text(encoding="utf-8")
    assert "RuntimeError: the disk went away" in log
    assert "could not be updated" not in log
    assert cli.rm_cmd(SimpleNamespace(id=run.name)) == 0
    assert not run.exists()
    capsys.readouterr()


@pytest.mark.parametrize("unknown", _UNKNOWN_STATES, ids=_UNKNOWN_IDS)
def test_a_run_whose_state_is_unknown_is_not_removed(run_dir, cli, capsys, unknown):
    (run_dir / "meta.json").write_text(unknown, encoding="utf-8")

    assert cli.rm_cmd(SimpleNamespace(id=run_dir.name)) == 1
    assert cli.prune_cmd(SimpleNamespace(keep=0)) == 0

    assert run_dir.exists()
    assert "refusing to remove an active or unreadable subagent" in capsys.readouterr().err


@pytest.mark.parametrize("status", ["ok", "fail", "timeout"])
def test_a_run_that_has_ended_is_still_removed(run_dir, cli, capsys, status):
    _write(run_dir / "meta.json", {"id": run_dir.name, "status": status})

    assert cli.rm_cmd(SimpleNamespace(id=run_dir.name)) == 0

    assert not run_dir.exists()
    capsys.readouterr()
