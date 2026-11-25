"""Windows Job Object that contains one command's process tree (#516)."""
# ``taskkill /T`` kills the tree it finds when it looks. A process created
# while the kill is running is not in that tree, and a tree whose first process
# has already exited cannot be found at all. A Job Object has neither gap:
# everything a member starts is a member from its first instruction, and the
# job is terminated as a whole.
#
# The module imports on every platform and touches Win32 only when called.
from __future__ import annotations

import ctypes
import functools
from ctypes import wintypes
from typing import Any

_KILL_ON_JOB_CLOSE = 0x2000
_EXTENDED_LIMIT_INFORMATION = 9
# PROCESS_TERMINATE | PROCESS_SET_QUOTA are what AssignProcessToJobObject
# asks for; PROCESS_SUSPEND_RESUME is what resuming asks for.
_HOLD_ACCESS = 0x0001 | 0x0100 | 0x0800


class _BasicLimits(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD)]


class _IoCounters(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint64) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimits(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _declare(library: Any, signatures: dict[str, tuple[list[Any], Any]]) -> Any:
    for name, (argtypes, restype) in signatures.items():
        function = getattr(library, name)
        function.argtypes = argtypes
        function.restype = restype
    return library


@functools.lru_cache(maxsize=1)
def _kernel32() -> Any:
    handle, dword, flag = wintypes.HANDLE, wintypes.DWORD, wintypes.BOOL
    return _declare(getattr(ctypes, "WinDLL")("kernel32", use_last_error=True), {
        "CreateJobObjectW": ([ctypes.c_void_p, wintypes.LPCWSTR], handle),
        "SetInformationJobObject": ([handle, ctypes.c_int, ctypes.c_void_p, dword], flag),
        "AssignProcessToJobObject": ([handle, handle], flag),
        "TerminateJobObject": ([handle, wintypes.UINT], flag),
        "OpenProcess": ([dword, flag, dword], handle),
        "CloseHandle": ([handle], flag),
    })


@functools.lru_cache(maxsize=1)
def _ntdll() -> Any:
    return _declare(getattr(ctypes, "WinDLL")("ntdll"), {
        "NtResumeProcess": ([wintypes.HANDLE], wintypes.LONG),
    })


def _failure(call: str) -> OSError:
    """The error of the Win32 call that just failed. Read it before any cleanup."""
    error = getattr(ctypes, "WinError")(getattr(ctypes, "get_last_error")())
    error.strerror = f"{call}: {error.strerror}"
    return error


class CommandJob:
    """A Job Object owned by one command; closing it kills whoever is still in it."""

    def __init__(self, handle: int) -> None:
        """Own an open job handle; `create` is the way to get one."""
        self._handle: int | None = handle

    @classmethod
    def create(cls) -> "CommandJob":
        handle = _kernel32().CreateJobObjectW(None, None)
        if not handle:
            raise _failure("CreateJobObjectW")
        job = cls(handle)
        try:
            job._limit(_KILL_ON_JOB_CLOSE)
        except OSError:
            job.close()
            raise
        return job

    def _open(self) -> int:
        if self._handle is None:
            raise OSError("the job object is closed")
        return self._handle

    def _limit(self, flags: int) -> None:
        limits = _ExtendedLimits()
        limits.BasicLimitInformation.LimitFlags = flags
        if not _kernel32().SetInformationJobObject(
                self._open(), _EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits)):
            raise _failure("SetInformationJobObject")

    def hold(self, pid: int) -> None:
        """Put a process that was created suspended into the job, then let it run."""
        # The process has executed nothing yet, so there is nothing it could
        # have started outside the job.
        kernel = _kernel32()
        job = self._open()
        process = kernel.OpenProcess(_HOLD_ACCESS, False, pid)
        if not process:
            raise _failure("OpenProcess")
        try:
            if not kernel.AssignProcessToJobObject(job, process):
                raise _failure("AssignProcessToJobObject")
            # Win32 resumes threads, and the handle of the first thread is not
            # available here: asyncio closes it. Finding the thread again means
            # a snapshot of every thread in the system, which took 22 ms of
            # event-loop time per command where this call took 0.07 ms.
            status = _ntdll().NtResumeProcess(process)
            if status:
                raise OSError(f"NtResumeProcess: status 0x{status & 0xFFFFFFFF:08X}")
        finally:
            kernel.CloseHandle(process)

    def terminate(self) -> None:
        """Kill every member, including one that is being created right now."""
        if not _kernel32().TerminateJobObject(self._open(), 1):
            raise _failure("TerminateJobObject")

    def disarm(self) -> None:
        """Closing the job no longer kills the members that are still running."""
        self._limit(0)

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None and not _kernel32().CloseHandle(handle):
            raise _failure("CloseHandle")
