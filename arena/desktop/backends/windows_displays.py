"""Display discovery for the Windows desktop backend: one entry per monitor (#514)."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from typing import Any

from arena.desktop.backends import _win32_api as _api

_MONITORINFOF_PRIMARY = 1
_MONITOR_DEFAULTTOPRIMARY = 1
_MDT_EFFECTIVE_DPI = 0
_DEVICE_PREFIX = "\\\\.\\"


class _MonitorInfo(ctypes.Structure):
    """MONITORINFOEXW."""

    _fields_ = [
        ("cbSize", wt.DWORD),
        ("rcMonitor", wt.RECT),
        ("rcWork", wt.RECT),
        ("dwFlags", wt.DWORD),
        ("szDevice", wt.WCHAR * 32),
    ]


# stdcall where it exists; elsewhere the plain prototype lets a stand-in for
# user32 call the callback in tests.
_ENUM_PROC = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)(
    wt.BOOL, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, wt.LPARAM)


def _geometry(rect: Any) -> dict[str, int]:
    return {
        "x": int(rect.left),
        "y": int(rect.top),
        "width": int(rect.right - rect.left),
        "height": int(rect.bottom - rect.top),
    }


def _bind(user: Any, shcore: Any) -> None:
    """Declare the handle-sized arguments; the default int cuts a 64-bit handle short."""
    user.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p, _ENUM_PROC, wt.LPARAM]
    user.GetMonitorInfoW.argtypes = [ctypes.c_void_p, ctypes.POINTER(_MonitorInfo)]
    user.MonitorFromWindow.argtypes = [ctypes.c_void_p, wt.DWORD]
    user.MonitorFromWindow.restype = ctypes.c_void_p
    if shcore is not None:
        shcore.GetDpiForMonitor.argtypes = [
            ctypes.c_void_p, ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]


def _monitor_dpi(shcore: Any, handle: int) -> int | None:
    """Return the monitor's effective DPI, or None before Windows 8.1 or on refusal."""
    horizontal, vertical = ctypes.c_uint(0), ctypes.c_uint(0)
    try:
        refused = shcore.GetDpiForMonitor(handle, _MDT_EFFECTIVE_DPI, ctypes.pointer(horizontal), ctypes.pointer(vertical))
    except (AttributeError, OSError):
        return None
    return None if refused or not horizontal.value else int(horizontal.value)


def _describe(index: int, info: Any, *, dpi: int | None, active: bool) -> dict[str, Any]:
    device = str(info.szDevice)
    return {
        "index": index,
        # "DISPLAY1" is what a person types; the device path is kept as the id.
        "name": device[len(_DEVICE_PREFIX):] if device.startswith(_DEVICE_PREFIX) else device,
        "id": device,
        "connected": True,
        "enabled": True,
        "primary": bool(info.dwFlags & _MONITORINFOF_PRIMARY),
        "active": active,
        "geometry": _geometry(info.rcMonitor),
        "work_area": _geometry(info.rcWork),
        "dpi": dpi,
        # 1.5 at "150 %". Geometry is already physical pixels; the scale is
        # for a client that wants to know how large things are drawn.
        "scale": None if dpi is None else round(dpi / 96, 2),
        "backend": "win32",
    }


def enumerate_displays(user: Any, shcore: Any) -> list[dict[str, Any]]:
    """Describe every monitor of the desktop, in physical pixels of the virtual screen."""
    handles: list[int] = []

    def remember(handle, _dc, _rect, _data):
        handles.append(handle)
        return 1

    _bind(user, shcore)
    callback = _ENUM_PROC(remember)
    if not user.EnumDisplayMonitors(None, None, callback, 0):
        raise OSError("EnumDisplayMonitors failed")
    # The display that has the foreground window; the primary one if there is none.
    active = user.MonitorFromWindow(user.GetForegroundWindow(), _MONITOR_DEFAULTTOPRIMARY)
    displays = []
    for handle in handles:
        info = _MonitorInfo(cbSize=ctypes.sizeof(_MonitorInfo))
        if user.GetMonitorInfoW(handle, ctypes.pointer(info)):
            displays.append(_describe(len(displays) + 1, info, dpi=_monitor_dpi(shcore, handle), active=handle == active))
    return displays


def _shcore() -> Any:
    """Return shcore.dll, or None on a Windows older than 8.1."""
    try:
        return ctypes.WinDLL("shcore") if sys.platform == "win32" else None
    except OSError:
        return None


def list_displays() -> list[dict[str, Any]]:
    """Describe the displays of this machine."""
    if sys.platform != "win32":
        raise NotImplementedError("windows backend not available on this platform")
    # Importing _win32_api has declared DPI awareness, so the rectangles
    # below are physical pixels, like screenshots and clicks (#513).
    return enumerate_displays(_api.user32, _shcore())
