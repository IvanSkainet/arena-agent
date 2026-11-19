"""Platform process inspection and conservative legacy task deadlines."""
from __future__ import annotations

from datetime import datetime
from typing import Any


def _windows_pid_is_alive(pid: int) -> bool:
    """Query a Windows process without signalling or terminating it.

    Access denied and unrecognised errors are treated as alive: reclaiming
    the record is unsafe unless the system positively reports a dead PID.
    """
    if pid > 0xFFFFFFFF:
        return True  # Win32 DWORD conversion must not truncate an unknown PID.
    import ctypes
    from ctypes import wintypes

    try:
        kernel = getattr(ctypes, "WinDLL")("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        handle = kernel.OpenProcess(0x00100000, False, pid)  # SYNCHRONIZE: query wait state, never signal it
        if not handle:
            return getattr(ctypes, "get_last_error")() != 87  # ERROR_INVALID_PARAMETER: no such PID
        try:
            result = kernel.WaitForSingleObject(handle, 0)
            return result != 0  # WAIT_OBJECT_0 means terminated, even with exit code259
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
