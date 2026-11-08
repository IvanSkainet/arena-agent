"""A task interrupted by a crashed bridge must stop claiming to be running.

A task file is written into `queue/running/` when a bridge claims it and is
removed when the run finishes. Kill the bridge in between and nothing ever
removes the file: `GET /v1/tasks` reports `running` for work that no process is
doing, `/health` stays `ok`, `/v1/tasks/clean` only trims `done/`+`failed/`, and
an agent waiting on that task waits forever. Missions have
`/v1/mission/recover`; tasks had nothing.

Reproduced on a live bridge (2026-11-07 durability round): task `sleep 45`,
wait for `running/<id>.json`, `kill -9` the bridge, restart, watch for 25 s --
state stayed `running`, and the child process kept working with nobody
recording its outcome.

The owner is now recorded in the task file (`pid`), and a start-up / per-tick
sweep moves records whose owner is gone into `failed` with `reason:
interrupted`. A record whose owner is *alive* is left alone: two bridges on one
home is a supported arrangement, and stealing a running task would be worse
than a stale line.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from arena.tasks.queue import pid_is_alive, reclaim_interrupted_tasks

NOW = "2026-11-07T12:00:00+00:00"


def _queue(tmp_path: Path) -> tuple[Path, Path]:
    running = tmp_path / "queue" / "running"
    failed = tmp_path / "queue" / "failed"
    running.mkdir(parents=True)
    return running, failed


def _write(running: Path, name: str, **fields) -> Path:
    task = {"id": name, "cmd": "sleep 60", "state": "running", "started_at": NOW}
    task.update(fields)
    path = running / f"{name}.json"
    path.write_text(json.dumps(task), encoding="utf-8")
    return path


def _sweep(running: Path, failed: Path, *, alive=None, grace: int = 60) -> dict:
    kwargs = {"alive": alive} if alive is not None else {}
    return reclaim_interrupted_tasks(
        running=running, failed=failed, now_fn=lambda: NOW, grace_seconds=grace, **kwargs
    )


def test_a_task_whose_owner_died_is_marked_interrupted(tmp_path):
    """The finding itself: this record used to be immortal."""
    running, failed = _queue(tmp_path)
    _write(running, "t1", pid=999_999_999)  # a pid that cannot be alive

    result = _sweep(running, failed, alive=lambda _: False)

    assert result["reclaimed"] == ["t1"]
    assert not (running / "t1.json").exists(), "the orphan is still in running/"
    moved = json.loads((failed / "t1.json").read_text(encoding="utf-8"))
    assert moved["state"] == "failed"
    assert moved["reason"] == "interrupted"
    assert moved["finished_at"] == NOW


def test_a_task_owned_by_a_live_process_is_left_alone(tmp_path):
    """Two bridges on one home is supported: never steal a live run."""
    running, failed = _queue(tmp_path)
    _write(running, "t2", pid=os.getpid())  # our own process is alive by definition

    result = _sweep(running, failed)

    assert result["reclaimed"] == []
    assert (running / "t2.json").exists(), "a live task was taken away from its owner"
    assert not (failed / "t2.json").exists()


def test_a_pid_less_record_is_left_alone_while_it_could_still_be_running(tmp_path):
    """Records written by older versions have no pid; do not guess too early."""
    running, failed = _queue(tmp_path)
    recent = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _write(running, "t3", started_at=recent, timeout=3600)

    result = _sweep(running, failed)

    assert result["reclaimed"] == []
    assert (running / "t3.json").exists()


def test_a_pid_less_record_is_reclaimed_once_its_own_timeout_has_passed(tmp_path):
    running, failed = _queue(tmp_path)
    ancient = (datetime.now(timezone.utc) - timedelta(seconds=7200)).isoformat(timespec="seconds")
    _write(running, "t4", started_at=ancient, timeout=60)

    result = _sweep(running, failed)

    assert result["reclaimed"] == ["t4"]
    assert json.loads((failed / "t4.json").read_text(encoding="utf-8"))["reason"] == "interrupted"


def test_unreadable_record_is_left_alone_during_possible_concurrent_write(tmp_path):
    running, failed = _queue(tmp_path)
    path = running / "t5.json"
    path.write_text('{"id": "t5", "cmd": "sl', encoding="utf-8")

    result = _sweep(running, failed)

    assert result["reclaimed"] == []
    assert path.exists()
    assert not (failed / "t5.json").exists()


def test_missing_started_at_does_not_steal_a_claim_in_progress(tmp_path):
    running, failed = _queue(tmp_path)
    path = running / "claim.json"
    path.write_text(json.dumps({"id": "claim", "state": "inbox"}), encoding="utf-8")

    assert _sweep(running, failed)["reclaimed"] == []
    assert path.exists()
    assert not (failed / path.name).exists()


def test_claim_window_and_malformed_records_do_not_block_other_recovery(tmp_path):
    running, failed = _queue(tmp_path)
    (running / "a.json").write_text(json.dumps({"id": "a", "state": "inbox"}), encoding="utf-8")
    (running / "b.json").write_text("[]", encoding="utf-8")
    _write(running, "c", pid=None, timeout={"bad": 1})
    _write(running, "d", pid=False)
    _write(running, "e", pid=999999999, id=None)

    result = _sweep(running, failed, alive=lambda _: False)

    assert result["reclaimed"] == ["e"]
    assert all((running / f"{name}.json").exists() for name in "abcd")
    assert json.loads((failed / "e.json").read_text(encoding="utf-8"))["id"] == "e"


def test_sweeping_twice_changes_nothing_the_second_time(tmp_path):
    """Recovery runs on every tick, so it must be a no-op on a healthy queue."""
    running, failed = _queue(tmp_path)
    _write(running, "t6", pid=999_999_999)
    _sweep(running, failed, alive=lambda _: False)
    before = (failed / "t6.json").read_bytes()

    result = _sweep(running, failed)

    assert result["reclaimed"] == []
    assert (failed / "t6.json").read_bytes() == before


def test_a_missing_running_directory_is_not_an_error(tmp_path):
    empty = tmp_path / "nowhere"
    result = reclaim_interrupted_tasks(
        running=empty, failed=tmp_path / "failed", now_fn=lambda: NOW
    )
    assert result == {"ok": True, "reclaimed": []}


def test_the_liveness_check_prefers_life_over_tidiness():
    """A wrong 'alive' leaves a visible stale line; a wrong 'dead' kills work."""
    assert pid_is_alive(os.getpid()) is True
    assert pid_is_alive(0) is False
    assert pid_is_alive(-1) is False
    # Unrecognised OS errors are intentionally treated as alive.



# --------------------------------------------------------------------------
# The sweep is only worth its tests if the loop actually calls it. Wiring a
# passing helper to nothing is the classic "gate nobody has seen execute".
# --------------------------------------------------------------------------
def test_the_runner_loop_actually_sweeps_the_running_directory(tmp_path, monkeypatch):
    import asyncio

    from arena.tasks import runner as runner_module
    from arena.tasks.queue import reclaim_interrupted_tasks as real_reclaim
    from arena.tasks.runner import TaskRunnerContext, make_task_runner_runtime

    def deterministic_reclaim(**kwargs):
        return real_reclaim(**kwargs, alive=lambda _: False)

    monkeypatch.setattr(runner_module, "reclaim_interrupted_tasks", deterministic_reclaim)

    running = tmp_path / "queue" / "running"
    inbox = tmp_path / "queue" / "inbox"
    done = tmp_path / "queue" / "done"
    failed = tmp_path / "queue" / "failed"
    for directory in (running, inbox, done, failed):
        directory.mkdir(parents=True)
    _write(running, "orphan", pid=999_999_999)

    logs: list[str] = []
    context = TaskRunnerContext(
        inbox=inbox,
        running=running,
        done=done,
        failed=failed,
        blocked_reason=lambda _cmd: None,
        cleanup_mcp_sessions=lambda: 0,
        utc_now=lambda: NOW,
        log_info=lambda fmt, *a: logs.append(fmt % a if a else fmt),
        log_error=lambda fmt, *a: logs.append(fmt % a if a else fmt),
    )
    runtime = make_task_runner_runtime(context)

    async def _one_tick() -> None:
        task = asyncio.create_task(runtime.runner_loop(None))  # the loop ignores `app`
        await asyncio.sleep(0.05)  # it sweeps before its first 5 s sleep
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(_one_tick())

    assert not (running / "orphan.json").exists(), (
        "the loop never called the sweep: the runner is wired to nothing"
    )
    assert json.loads((failed / "orphan.json").read_text(encoding="utf-8"))["reason"] == "interrupted"
    assert any("Reclaimed" in line for line in logs), "the reclaim was silent"


def test_completed_result_is_not_overwritten_or_reclassified(tmp_path):
    running, failed = _queue(tmp_path)
    done = running.parent / "done"
    done.mkdir()
    _write(running, "finished", pid=999_999_999)
    result_path = done / "finished.json"
    result_path.write_text('{"id":"finished","state":"done","exit_code":0}', encoding="utf-8")

    result = reclaim_interrupted_tasks(
        running=running, failed=failed, done=done, now_fn=lambda: NOW, alive=lambda _: False,
    )
    assert result["reclaimed"] == []
    assert result_path.read_text(encoding="utf-8") == '{"id":"finished","state":"done","exit_code":0}'
    assert not (failed / "finished.json").exists()


def test_existing_failed_result_is_never_overwritten(tmp_path):
    running, failed = _queue(tmp_path)
    failed.mkdir()
    _write(running, "finished", pid=999_999_999)
    result_path = failed / "finished.json"
    result_path.write_text('{"important":"original"}', encoding="utf-8")

    _sweep(running, failed, alive=lambda _: False)
    assert result_path.read_text(encoding="utf-8") == '{"important":"original"}'


def test_reclaim_storage_error_is_reported_and_source_remains(tmp_path, monkeypatch):
    from arena.tasks import queue
    running, failed = _queue(tmp_path)
    _write(running, "orphan", pid=999_999_999)

    def deny(*args, **kwargs):
        raise PermissionError("link unavailable")

    monkeypatch.setattr(queue.os, "link", deny)
    result = _sweep(running, failed, alive=lambda _: False)
    assert result["ok"] is False
    assert any("link unavailable" in error for error in result["errors"])
    assert (running / "orphan.json").exists()
    assert not (failed / "orphan.json").exists()


def _race_sweeper(running, failed, barrier, results):
    from arena.tasks import queue

    original_link = queue.os.link

    def synchronized_link(*args, **kwargs):
        barrier.wait(timeout=15)
        return original_link(*args, **kwargs)

    queue.os.link = synchronized_link
    try:
        result = queue.reclaim_interrupted_tasks(
            running=Path(running), failed=Path(failed), now_fn=lambda: NOW, alive=lambda _: False,
        )
        results.put(result)
    except Exception as exc:
        results.put({"exception": repr(exc)})


def test_two_processes_cannot_overwrite_the_same_recovery_result(tmp_path):
    import multiprocessing

    running, failed = _queue(tmp_path)
    _write(running, "racing", pid=999_999_999)
    context = multiprocessing.get_context("spawn")
    barrier, results = context.Barrier(2), context.Queue()
    processes = [context.Process(target=_race_sweeper, args=(str(running), str(failed), barrier, results))
                 for _ in range(2)]
    for process in processes:
        process.start()
    try:
        for process in processes:
            process.join(25)
            assert process.exitcode == 0
        outputs = [results.get(timeout=5) for _ in processes]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join()
    assert all(result.get("ok") for result in outputs), outputs
    assert sorted(len(result["reclaimed"]) for result in outputs) == [0, 1]
    assert not (running / "racing.json").exists()
    assert json.loads((failed / "racing.json").read_text(encoding="utf-8"))["reason"] == "interrupted"
