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

_JOB: Any = None


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
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=10)


def _parent_pipe(cancelled: threading.Event) -> None:
    os.read(sys.stdin.fileno(), 1)
    cancelled.set()


def _collect(process: subprocess.Popen, cancelled: threading.Event, timeout: float) -> int:
    deadline = time.monotonic() + timeout
    while True:
        if cancelled.is_set():
            _stop_tree(process)
            return 125
        if time.monotonic() >= deadline:
            _stop_tree(process)
            sys.stderr.write("timeout")
            return 124
        try:
            stdout, stderr = process.communicate(timeout=0.2)
        except subprocess.TimeoutExpired:
            continue
        sys.stdout.buffer.write(stdout)
        sys.stderr.buffer.write(stderr)
        return process.returncode


def main() -> int:
    if len(sys.argv) != 2:
        return 2
    task = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    if os.name == "nt":
        _windows_job()
    cancelled = threading.Event()
    threading.Thread(target=_parent_pipe, args=(cancelled,), daemon=True).start()
    # Deliberately the same authorized task shell contract as the old runner;
    # the command is not interpolated into an additional launcher shell.
    process = subprocess.Popen(task["cmd"], shell=True, cwd=os.path.expanduser(task.get("cwd") or str(Path.home())),  # nosec B602 -- explicitly authorized task-runner shell command, already checked by the bridge policy  # nosemgrep: subprocess-shell-true, dangerous-subprocess-use-tainted-env-args -- task execution is the authorized shell-command API; private queue input is policy-checked in runner before spawning this isolated worker
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               close_fds=True, start_new_session=os.name != "nt")
    try:
        return _collect(process, cancelled, float(task.get("timeout") or 3600))
    finally:
        if process.poll() is None:
            _stop_tree(process)


if __name__ == "__main__":
    raise SystemExit(main())
