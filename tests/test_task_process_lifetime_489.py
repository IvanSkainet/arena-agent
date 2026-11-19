"""Real subprocess lease: owner death and timeout must reap task descendants."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path
from unittest import TestCase

import psutil
import pytest

from arena.tasks import process_worker

CHECK = TestCase()
WORKER = Path(process_worker.__file__).resolve()


def _alive(pid: int) -> bool:
    try:
        process = psutil.Process(pid)
        return process.is_running()
    except psutil.NoSuchProcess:
        return False


def _owned_tree_finished(pids: list[int], worker_pid: int) -> bool:
    for pid in pids:
        try:
            process = psutil.Process(pid)
            # After its parent is killed, only the OS init/subreaper can reap
            # this worker. A zombie proves it honored EOF and exited; command
            # descendants must still disappear entirely (no zombie allowance).
            if pid == worker_pid and process.status() == psutil.STATUS_ZOMBIE:
                continue
            if process.is_running():
                return False
        except psutil.NoSuchProcess:
            continue
    return True


def _wait_until(predicate, timeout: float = 15) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.02)
    CHECK.fail("subprocess lifetime condition did not become true before deadline")


def _task(tmp_path: Path, timeout: int) -> tuple[Path, Path]:
    marker = tmp_path / "children.json"
    child = tmp_path / "child.py"
    child.write_text(
        "import subprocess, sys, os, json, time\nfrom pathlib import Path\n"
        "grandchild = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(90)'])\n"
        f"Path({str(marker)!r}).write_text(json.dumps([os.getpid(), grandchild.pid]))\n"
        "time.sleep(90)\n", encoding="utf-8")
    argv = [sys.executable, str(child)]
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    task = tmp_path / "task.json"
    task.write_text(json.dumps({"cmd": command, "cwd": str(tmp_path), "timeout": timeout}))
    return task, marker


def _marker_pids(marker: Path) -> list[int] | None:
    try:
        return json.loads(marker.read_text())
    except (OSError, ValueError):
        return None


def _require_marker_pids(marker: Path) -> list[int]:
    pids = _marker_pids(marker)
    if pids is None:
        raise AssertionError("fixture did not publish complete child PIDs")
    return pids


def _cleanup(pids: list[int]) -> None:
    # Only PIDs recorded by these temporary fixture processes, never a bridge
    # lookup, executable-name wildcard or fixed service port.
    for pid in pids:
        if _alive(pid):
            psutil.Process(pid).kill()


def test_killing_the_owner_reaps_the_child_and_grandchild(tmp_path):
    task, marker = _task(tmp_path, 60)
    worker_pid = tmp_path / "worker.pid"
    owner = tmp_path / "owner.py"
    owner.write_text(
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        f"worker=subprocess.Popen([sys.executable,'-I',{str(WORKER)!r},{str(task)!r}], "
        "stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
        f"Path({str(worker_pid)!r}).write_text(str(worker.pid))\n"
        "time.sleep(90)\n", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "-I", str(owner)],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    pids = []
    try:
        _wait_until(lambda: _marker_pids(marker) is not None)
        pids = _require_marker_pids(marker)
        CHECK.assertTrue(all(_alive(pid) for pid in pids))
        recorded_worker = int(worker_pid.read_text())
        pids.append(recorded_worker)
        CHECK.assertTrue(all(_alive(pid) for pid in pids))
        process.kill()
        process.wait(timeout=5)
        _wait_until(lambda: _owned_tree_finished(pids, recorded_worker))
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        if marker.exists():
            pids.extend(json.loads(marker.read_text()))
        _cleanup(pids)


def test_timeout_reaps_the_child_and_grandchild(tmp_path):
    task, marker = _task(tmp_path, 1)
    process = subprocess.Popen([sys.executable, "-I", str(WORKER), str(task)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pids = []
    try:
        _wait_until(lambda: _marker_pids(marker) is not None)
        pids = _require_marker_pids(marker)
        CHECK.assertTrue(all(_alive(pid) for pid in pids))
        # wait(), not communicate(): stdin is the lease and must remain open.
        returncode = process.wait(timeout=15)
        stdout, stderr = process.communicate(timeout=3)
        CHECK.assertEqual(returncode, 124, stderr.decode(errors="replace"))
        CHECK.assertEqual(stdout, b"")
        CHECK.assertIn(b"timeout", stderr)
        _wait_until(lambda: not any(_alive(pid) for pid in pids))
    finally:
        if process.stdin is not None:
            process.stdin.close()
        if process.poll() is None:
            process.kill()
        process.wait(timeout=5)
        _cleanup(pids)


def test_worker_drains_large_output_but_retains_only_budget_plus_sentinel(tmp_path):
    script = tmp_path / "noisy.py"
    script.write_text("import sys\nsys.stdout.write('x' * 8_000_000)\nsys.stderr.write('y' * 8_000_000)\n")
    argv = [sys.executable, str(script)]
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    task = tmp_path / "bounded.json"
    task.write_text(json.dumps({"cmd": command, "cwd": str(tmp_path),
                                "timeout": 15, "max_output": 1000}))
    process = subprocess.Popen([sys.executable, "-I", str(WORKER), str(task)],
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        # Keep the owner lease open until the worker drains both child pipes.
        CHECK.assertEqual(process.wait(timeout=20), 0)
        stdout, stderr = process.communicate(timeout=3)
        CHECK.assertEqual(stdout, b"x" * 1001)
        CHECK.assertEqual(stderr, b"y" * 1001)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


@pytest.mark.skipif(sys.platform != "linux", reason="Linux subreaper and setsid containment")
def test_successful_shell_reaps_descendant_that_escapes_its_process_group(tmp_path):
    marker = tmp_path / "escaped.pid"
    script = tmp_path / "escape.py"
    script.write_text(
        "import subprocess,sys\nfrom pathlib import Path\n"
        "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(90)'],start_new_session=True)\n"
        f"Path({str(marker)!r}).write_text(str(child.pid))\n", encoding="utf-8")
    task = tmp_path / "escape-task.json"
    task.write_text(json.dumps({"cmd": shlex.join([sys.executable, str(script)]),
                                "cwd": str(tmp_path), "timeout": 10}), encoding="utf-8")
    worker = subprocess.Popen([sys.executable, "-I", str(WORKER), str(task)],
                              stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    pids = []
    try:
        _wait_until(marker.exists)
        pids = [int(marker.read_text())]
        CHECK.assertEqual(worker.wait(timeout=15), 0)
        _wait_until(lambda: not any(_alive(pid) for pid in pids))
    finally:
        if worker.stdin is not None:
            worker.stdin.close()
        if worker.poll() is None:
            worker.kill()
        worker.wait(timeout=10)
        if marker.exists():
            pids = [int(marker.read_text())]
        _cleanup(pids)
