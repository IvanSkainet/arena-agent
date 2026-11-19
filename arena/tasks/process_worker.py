"""Task child lifetime follows a private parent-owned stdin pipe (T73).

The bridge holds the write end open. EOF means cancellation or owner death,
including an uncatchable owner termination. The worker never passes that
handle to the actual command, so descendants cannot keep the lease alive.
Windows additionally contains this worker and descendants in a kill-on-close
Job Object; its handle is deliberately held until process exit.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess  # nosec B404 -- authorized task shell worker; parent owns policy enforcement and lifetime
import sys
import threading
import time
from pathlib import Path
from typing import Any
from weakref import WeakSet

_JOB: Any = None
_STOPPED_GROUPS: WeakSet[subprocess.Popen] = WeakSet()


def _adopt_descendants() -> None:
    if sys.platform != "linux":
        return
    import ctypes

    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
        raise OSError(ctypes.get_errno(), "cannot supervise adopted descendants")


def _adopted_child_ids() -> list[int]:
    children_ids = []
    for children in Path(f"/proc/{os.getpid()}/task").glob("*/children"):
        try:
            children_ids.extend(int(child) for child in children.read_text().split())
        except FileNotFoundError:
            continue
    return children_ids


def _kill_adopted_children() -> None:
    # A subreaper also owns children that escaped with setsid(). No wait in
    # this thread can reap them between reading their PID and signalling it.
    for child in _adopted_child_ids():
        try:
            os.kill(child, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _reap_descendants() -> None:
    if sys.platform != "linux":
        return
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        _kill_adopted_children()
        try:
            pid, _status = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            time.sleep(.01)


def _windows_job() -> None:
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in
                    ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimits), ("IoInfo", IoCounters),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        error = getattr(ctypes, "get_last_error")()
        kernel.CloseHandle(job)
        raise getattr(ctypes, "WinError")(error)
    if not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess()):
        error = getattr(ctypes, "get_last_error")()
        kernel.CloseHandle(job)
        raise getattr(ctypes, "WinError")(error)
    global _JOB
    _JOB = job  # OS closes it at process exit, after the selected exit status.


def _stop_tree(process: subprocess.Popen) -> None:
    if os.name == "nt":
        # The process-lifetime Job Object remains the final backstop, including
        # when the command shell has already exited before its descendants.
        cleanup = ["taskkill", "/PID", str(process.pid), "/T", "/F"]
        subprocess.run(cleanup, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)  # nosec B603 -- fixed Windows cleanup utility + owned child PID, never caller input
    elif process not in _STOPPED_GROUPS:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        # Cleanup runs from timeout, collection and finally. Once SIGKILL
        # succeeded, repeating it can hit Darwin zombie-group EPERM (or a
        # reused numeric group). Keep identity on the Popen object, not PID.
        _STOPPED_GROUPS.add(process)
    process.wait(timeout=10)


def _parent_pipe(cancelled: threading.Event) -> None:
    os.read(sys.stdin.fileno(), 1)
    cancelled.set()


def _drain_pipe(source, destination, limit: int) -> None:
    """Drain continuously while retaining at most the configured output budget."""
    retained = 0
    while chunk := source.read(65536):
        keep = chunk[:max(0, limit - retained)]
        destination.write(keep)
        retained += len(keep)
    destination.flush()


def _wait_for_command(process: subprocess.Popen, cancelled: threading.Event, deadline: float) -> int | None:
    result = None
    while process.poll() is None:
        if cancelled.is_set():
            _stop_tree(process)
            result = 125
            break
        if time.monotonic() >= deadline:
            _stop_tree(process)
            result = 124
            break
        time.sleep(.02)
    return result


def _collect(process: subprocess.Popen, cancelled: threading.Event, timeout: float,
                max_output: int = 2_000_000, result_path: Path | None = None) -> int:
    readers = [threading.Thread(target=_drain_pipe, args=(source, target, max_output + 1), daemon=True)
                for source, target in ((process.stdout, sys.stdout.buffer),
                                        (process.stderr, sys.stderr.buffer))]
    for reader in readers:
        reader.start()
    deadline = time.monotonic() + timeout
    result = _wait_for_command(process, cancelled, deadline)
    _stop_tree(process)
    _reap_descendants()
    for reader in readers:
        reader.join(timeout=10)
    if result == 124:
        sys.stderr.write("timeout")
    statuses: dict[int | None, str] = {124: "timeout", 125: "cancelled"}
    status = statuses.get(result, "exited")
    if result_path is not None:
        _write_worker_result(result_path, status)
    return process.returncode if result is None else result


def _write_worker_result(path: Path, status: str) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        if os.name != "nt":
            os.fchmod(stream.fileno(), 0o600)
        json.dump({"status": status}, stream)


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    task = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if os.name == "nt":
        _windows_job()
    _adopt_descendants()
    cancelled = threading.Event()
    threading.Thread(target=_parent_pipe, args=(cancelled,), daemon=True).start()
    # Deliberately the same authorized task shell contract as the old runner;
    # the command is not interpolated into an additional launcher shell.
    process = subprocess.Popen(task["cmd"], shell=True, cwd=os.path.expanduser(task.get("cwd") or str(Path.home())),  # nosec B602 -- explicitly authorized task-runner shell command, already checked by the bridge policy  # nosemgrep: subprocess-shell-true, dangerous-subprocess-use-tainted-env-args -- task execution is the authorized shell-command API; private queue input is policy-checked in runner before spawning this isolated worker
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                close_fds=True, start_new_session=os.name != "nt")
    try:
        return _collect(process, cancelled, float(task.get("timeout") or 3600),
                        int(task.get("max_output") or 2_000_000),
                        Path(sys.argv[1]).with_suffix(".result.json") if task.get("record_result") else None)
    finally:
        _stop_tree(process)
        _reap_descendants()


if __name__ == "__main__":
    raise SystemExit(main())
