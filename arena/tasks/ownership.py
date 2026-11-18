"""Platform process inspection and conservative legacy task deadlines."""
from __future__ import annotations

from datetime import datetime
from typing import Any


def _windows_pid_is_alive(pid: int) -> bool:
    """Query a Windows process without signalling or terminating it.

    Access denied and unrecognised errors are treated as alive: reclaiming
    the record is unsafe unless the system positively reports a dead PID.
    """
    import ctypes
    from ctypes import wintypes

    try:
        kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetExitCodeProcess.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return getattr(ctypes, "get_last_error")() != 87  # ERROR_INVALID_PARAMETER: no such PID
        try:
            exit_code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return True
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    except (AttributeError, OSError, ValueError, OverflowError):
        return True


def _past_its_deadline(task: dict[str, Any], now_epoch: float, grace_seconds: int) -> bool:
    """True when a pid-less record is old enough that nobody can be running it."""
    try:
        started = datetime.fromisoformat(str(task.get("started_at", ""))).timestamp()
    except (TypeError, ValueError, OverflowError, OSError):
        # Missing metadata can be the window between claim and metadata write.
        return False
    try:
        timeout = int(task.get("timeout") or 3600)
    except (TypeError, ValueError, OverflowError):
        return False
    if timeout <= 0:
        return False
    return now_epoch - started > timeout + grace_seconds
