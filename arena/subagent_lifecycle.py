"""Detached subagent supervision using the same owned task lease as the bridge."""
from __future__ import annotations

import contextlib
import json
import os
import subprocess  # nosec B404 -- fixed interpreter launches the private owned task worker
import sys
import time
import traceback
from pathlib import Path

from arena.private_state import write_private_json

META_FILE = "meta.json"
MONITOR_LOG = "monitor-error.log"
_ACTIVE = frozenset({"running", "spawned"})


def output_tail(path: Path, lines: int) -> str:
    if lines <= 0:
        return ""
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def _private_output(path: Path):
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        path.chmod(0o600)
        return os.fdopen(fd, "wb")
    except BaseException:
        os.close(fd)
        raise


def _worker_timed_out(task: Path) -> bool:
    try:
        result = json.loads(task.with_suffix(".result.json").read_text(encoding="utf-8"))
        return result.get("status") == "timeout"
    except (OSError, ValueError, AttributeError):
        return False  # A crashed worker is a failure, not proof of timeout.


def run(directory: Path) -> dict:
    meta = json.loads((directory / META_FILE).read_text(encoding="utf-8"))
    out_path, err_path = directory / "stdout.log", directory / "stderr.log"
    started = time.monotonic()
    task = directory / "task.json"
    write_private_json(task, {"cmd": meta["cmd"], "cwd": meta["cwd"],
                              "timeout": meta["timeout"], "max_output": 2_000_000, "record_result": True})
    worker = Path(__file__).with_name("tasks") / "process_worker.py"
    with _private_output(out_path) as stdout, _private_output(err_path) as stderr:
        process = subprocess.Popen([sys.executable, "-I", str(worker), str(task)],  # nosec B603 -- fixed interpreter and package-owned worker; task is private operator input, never an executable path
                                   stdin=subprocess.PIPE, stdout=stdout, stderr=stderr,
                                   env=os.environ.copy(), close_fds=True)
        try:
            rc = process.wait(timeout=float(meta["timeout"]) + 20)
            timed_out = _worker_timed_out(task)
        except subprocess.TimeoutExpired:
            from arena.tasks.runner import kill_worker_tree

            kill_worker_tree(process.pid)
            process.wait(timeout=10)
            rc = 124
            timed_out = True
        finally:
            if process.stdin is not None:
                process.stdin.close()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
    status = "timeout" if timed_out else "fail"
    if rc == 0:
        status = "ok"
    duration = round(time.monotonic() - started, 3)
    summary = {"id": meta["id"], "name": meta["name"], "status": status, "exit": rc,
               "duration_sec": duration, "stdout_tail": output_tail(out_path, meta["max_out"]),
               "stderr_tail": output_tail(err_path, 30),
               "paths": {"stdout": str(out_path), "stderr": str(err_path), "dir": str(directory)}}
    write_private_json(directory / "summary.json", summary)
    meta.update(status=status, exit=rc, duration_sec=duration)
    write_private_json(directory / META_FILE, meta)
    return summary


def supervise(directory: Path) -> dict:
    """Run the command; a failure of the supervision itself is recorded, then raised (#602)."""
    try:
        return run(directory)
    except Exception as failure:
        _record_failure(directory, failure)
        raise


def _record_failure(directory: Path, failure: Exception) -> None:
    # A detached monitor has no stderr anyone reads, and a run it abandons
    # would look active for good: `rm` and `prune` refuse an active run.
    # Leave the traceback in the run directory and end the run as failed.
    notes = ["".join(traceback.format_exception(type(failure), failure, failure.__traceback__))]
    error = f"monitor failed: {failure!r}"[:500]
    # meta.json last, as in run(): it is the file that says a run has ended.
    for name in ("summary.json", META_FILE):
        try:
            _end_as_failed(directory / name, error)
        except FileNotFoundError:
            continue  # A waiting run has no summary yet; nothing to correct.
        except (OSError, ValueError, AttributeError, TypeError, RecursionError) as second:
            notes.append(f"{name} could not be updated: {second!r}\n")
    with contextlib.suppress(OSError), _private_output(directory / MONITOR_LOG) as log:
        log.write("".join(notes).encode("utf-8", errors="replace"))


def _end_as_failed(path: Path, error: str) -> None:
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("status") not in _ACTIVE:
        return  # Already ended: what was recorded stays.
    state.update(status="fail", error=error)
    write_private_json(path, state)


if __name__ == "__main__":
    supervise(Path(sys.argv[1]))
