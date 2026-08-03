"""Raw Windows API bindings + BMP helpers for the windows backend.

Split out of ``arena/desktop/backends/windows.py`` in v4.81.1 so
the caller-facing module stays under the 600-line
"modular runtime" threshold enforced by
``tests/test_architecture_boundaries.py``.

This file is intentionally boring: it declares argtypes/restypes
for every ``user32``/``gdi32`` symbol we call and exposes a
handful of Windows constants (``SW_*``, ``SWP_*``, ``MOUSEEVENTF_*``,
``KEYEVENTF_*``, ``VK_*``, ``VK_MAP``). It also owns the two BMP
helpers (``hbitmap_to_png_bytes`` / ``raw_bgra_to_bmp``) that read
raw pixels off an HBITMAP and produce PNG (via Pillow) or BMP
(pure-Python fallback) bytes.

Non-Windows platforms get None sentinels so ``from ... import``
never blows up during test collection on Linux.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import io
import sys
from typing import Any

_IS_WINDOWS = sys.platform == "win32"


# Declared `Any` rather than left to inference. On a non-Windows checkout the
# `else` branch below binds these to None, which would otherwise make every
# `user32.GetForegroundWindow(...)` in the backend read as an attribute access
# on None -- 59 findings in windows.py alone, none of them real: the module is
# only ever reached behind `_IS_WINDOWS`. ctypes.windll has no useful static
# type anyway, so nothing is lost by saying so explicitly.
user32: Any
gdi32: Any
kernel32: Any
dwmapi: Any
EnumWindowsProc: Any

# `ctypes.windll` only exists in the Windows build of the stdlib, so every
# reference to it reads as a missing attribute when the checker runs on Linux
# (which CI does). Routing through an `Any`-typed alias keeps the guarded code
# honest without pretending the attribute is portable.
_ct: Any = ctypes
# Assigning the None sentinels through an `Any` binding stops the checker from
# collapsing the declared `Any` back to `NoneType` for the whole module.
_UNAVAILABLE: Any = None

if _IS_WINDOWS:
    user32 = _ct.windll.user32
    gdi32 = _ct.windll.gdi32
    kernel32 = _ct.windll.kernel32
    dwmapi = _ct.windll.dwmapi

    user32.GetForegroundWindow.restype = wt.HWND
    user32.SetForegroundWindow.argtypes = [wt.HWND]
    user32.SetForegroundWindow.restype = wt.BOOL
    user32.BringWindowToTop.argtypes = [wt.HWND]
    user32.BringWindowToTop.restype = wt.BOOL
    user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wt.BOOL
    user32.IsWindow.argtypes = [wt.HWND]
    user32.IsWindow.restype = wt.BOOL
    user32.IsWindowVisible.argtypes = [wt.HWND]
    user32.IsWindowVisible.restype = wt.BOOL
    user32.IsIconic.argtypes = [wt.HWND]
    user32.IsIconic.restype = wt.BOOL
    user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowTextLengthW.argtypes = [wt.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.GetWindowRect.restype = wt.BOOL
    user32.GetClientRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
    user32.GetClientRect.restype = wt.BOOL
    user32.ClientToScreen.argtypes = [wt.HWND, ctypes.POINTER(wt.POINT)]
    user32.ClientToScreen.restype = wt.BOOL
    dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
    user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    user32.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
    user32.SetWindowPos.restype = wt.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wt.BOOL
    user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
    user32.GetCursorPos.restype = wt.BOOL
    user32.mouse_event.argtypes = [wt.DWORD, wt.DWORD, wt.DWORD, wt.DWORD, ctypes.c_void_p]
    user32.mouse_event.restype = None
    user32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.c_void_p]
    user32.keybd_event.restype = None
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.VkKeyScanW.argtypes = [ctypes.c_wchar]
    user32.VkKeyScanW.restype = ctypes.c_short
    user32.GetDesktopWindow.restype = wt.HWND
    user32.GetDC.argtypes = [wt.HWND]
    user32.GetDC.restype = wt.HDC
    user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
    user32.ReleaseDC.restype = ctypes.c_int

    gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
    gdi32.CreateCompatibleDC.restype = wt.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
    gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
    gdi32.SelectObject.restype = wt.HGDIOBJ
    gdi32.BitBlt.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.HDC, ctypes.c_int, ctypes.c_int, wt.DWORD]
    gdi32.BitBlt.restype = wt.BOOL
    gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
    gdi32.DeleteObject.restype = wt.BOOL
    gdi32.DeleteDC.argtypes = [wt.HDC]
    gdi32.DeleteDC.restype = wt.BOOL

    EnumWindowsProc = _ct.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows.argtypes = [EnumWindowsProc, wt.LPARAM]
    user32.EnumWindows.restype = wt.BOOL
    user32.EnumChildWindows.argtypes = [wt.HWND, EnumWindowsProc, wt.LPARAM]
    user32.EnumChildWindows.restype = wt.BOOL
else:
    # Stubs so tests can import the module on Linux.
    user32 = _UNAVAILABLE
    gdi32 = _UNAVAILABLE
    kernel32 = _UNAVAILABLE
    dwmapi = _UNAVAILABLE
    EnumWindowsProc = _UNAVAILABLE


# ---------------------------------------------------------------------------
# Constants (safe to expose on every platform)
# ---------------------------------------------------------------------------
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SW_RESTORE = 9

SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040
HWND_TOP = 0
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2

MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

VK_LMENU = 0x12

SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79

SRCCOPY = 0x00CC0020

VK_MAP: dict[str, int] = {
    "return": 0x0D, "enter": 0x0D, "escape": 0x1B, "esc": 0x1B, "tab": 0x09,
    "backspace": 0x08, "delete": 0x2E, "space": 0x20,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "f1": 0x70, "f2": 0x71, "f3": 0x72, "f4": 0x73, "f5": 0x74, "f6": 0x75,
    "f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "f11": 0x7A, "f12": 0x7B,
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12,
    "win": 0x5B, "super": 0x5B, "lwin": 0x5B, "rwin": 0x5C,
    "insert": 0x2D, "printscreen": 0x2C, "menu": 0x5D, "apps": 0x5D,
}


# ---------------------------------------------------------------------------
# HBITMAP -> PNG/BMP bytes.
# ---------------------------------------------------------------------------
def hbitmap_to_png_bytes(hbmp: int, width: int, height: int) -> bytes:
    """Extract pixels from HBITMAP and encode as PNG (fallback BMP).

    Uses Pillow when available for real PNG output; otherwise wraps
    the raw BGRA pixels in a BMP header (still a valid image; the
    caller can detect PNG vs BMP via magic bytes).
    """
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wt.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wt.WORD),
            ("biBitCount", wt.WORD),
            ("biCompression", wt.DWORD),
            ("biSizeImage", wt.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wt.DWORD),
            ("biClrImportant", wt.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wt.DWORD * 3)]

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # negative = top-down (BGRA order)
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = 0  # BI_RGB
    bmi.bmiHeader.biSizeImage = width * height * 4

    buf = (ctypes.c_ubyte * (width * height * 4))()
    hwnd_desktop = user32.GetDesktopWindow()
    hdc_screen = user32.GetDC(hwnd_desktop)
    try:
        gdi32.GetDIBits = _ct.windll.gdi32.GetDIBits
        gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wt.UINT]
        gdi32.GetDIBits.restype = ctypes.c_int
        got = gdi32.GetDIBits(hdc_screen, hbmp, 0, height, buf, ctypes.byref(bmi), 0)
        if got == 0:
            raise OSError("GetDIBits returned 0")
    finally:
        user32.ReleaseDC(hwnd_desktop, hdc_screen)

    raw = bytes(buf)

    try:
        from PIL import Image  # type: ignore
        img = Image.frombuffer("RGBA", (width, height), raw, "raw", "BGRA", 0, 1)
        img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=False)
        return out.getvalue()
    except Exception:
        return raw_bgra_to_bmp(raw, width, height)


def raw_bgra_to_bmp(pixels: bytes, width: int, height: int) -> bytes:
    """Wrap raw BGRA pixels in a BITMAPFILEHEADER + BITMAPINFOHEADER."""
    file_size = 14 + 40 + len(pixels)
    header = bytearray()
    header += b"BM"
    header += file_size.to_bytes(4, "little")
    header += b"\x00\x00\x00\x00"
    header += (14 + 40).to_bytes(4, "little")
    header += (40).to_bytes(4, "little")
    header += width.to_bytes(4, "little", signed=True)
    header += (-height).to_bytes(4, "little", signed=True)
    header += (1).to_bytes(2, "little")
    header += (32).to_bytes(2, "little")
    header += (0).to_bytes(4, "little")
    header += len(pixels).to_bytes(4, "little")
    header += (0).to_bytes(4, "little")
    header += (0).to_bytes(4, "little")
    header += (0).to_bytes(4, "little")
    header += (0).to_bytes(4, "little")
    return bytes(header) + pixels
