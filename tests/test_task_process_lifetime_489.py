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

from arena.tasks import process_worker

CHECK = TestCase()
WORKER = Path(process_worker.__file__).resolve()


def _alive(pid: int) -> bool:
    try:
        process = psutil.Process(pid)
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


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
        _wait_until(marker.exists)
        pids = json.loads(marker.read_text())
        pids.append(int(worker_pid.read_text()))
        CHECK.assertTrue(all(_alive(pid) for pid in pids))
        process.kill()
        process.wait(timeout=5)
        _wait_until(lambda: not any(_alive(pid) for pid in pids))
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
        _wait_until(marker.exists)
        pids = json.loads(marker.read_text())
        # wait(), not communicate(): stdin is the lease and must remain open.
        CHECK.assertEqual(process.wait(timeout=15), 124)
        stdout, stderr = process.communicate(timeout=3)
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
