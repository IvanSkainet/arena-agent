"""Windows backend for the desktop automation surface.

This module ships with v4.81.0. Before it, every helper in
``arena/desktop/*.py`` shelled out to ``spectacle`` / ``grim`` /
``scrot`` / ``xdotool`` / ``ydotool``, which meant every
``/v1/desktop/*`` endpoint returned ``"No screenshot tool
available"`` on Windows even though the Windows API surface
exposes everything natively via ``user32.dll`` + ``gdi32.dll``.

The module is stdlib-only (``ctypes``). ``Pillow`` is used
opportunistically for JPEG/WebP transforms; PNG output is
produced by hand-written BITMAPFILEHEADER + BITMAPINFOHEADER
so a minimal install still gets PNG-compatible bytes (in fact
we emit BMP under a ``.png`` extension only if Pillow is
missing — the caller can transcode).

Design notes:

* We never call ``AttachThreadInput`` between an elevated and
  a non-elevated thread. Windows blocks that transition and
  returns False silently. Instead, ``focus_window`` uses the
  well-known "press ALT once, then SetForegroundWindow" trick
  that releases the foreground lock.
* ``MainWindowHandle`` from ``Get-Process`` lies for Delphi /
  Lazarus / LCL apps (Cheat Engine, Delphi installers,
  Rad Studio). The real user-facing window is a ``TCustomForm``
  or ``TFormMain`` window, not the top-level ``TApplication``
  frame. ``list_windows`` walks every visible top-level window
  regardless of process ``MainWindowHandle`` and returns the
  full set, so callers can pick the visible one.
* Every function is a plain sync call. The caller wraps in
  ``run_in_executor`` where needed. Keeping the backend sync
  makes it easy to test on Windows without an asyncio loop.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import io
import sys
import time
from typing import Any

_IS_WINDOWS = sys.platform == "win32"


# ---------------------------------------------------------------------------
# ctypes signatures. Kept module-level so we don't re-declare on every call.
# ---------------------------------------------------------------------------
if _IS_WINDOWS:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32

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

    _EnumWindowsProc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    user32.EnumWindows.argtypes = [_EnumWindowsProc, wt.LPARAM]
    user32.EnumWindows.restype = wt.BOOL

    # Constants we use throughout.
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

    VK_LMENU = 0x12  # left ALT — used for foreground-lock release

    SM_CXSCREEN = 0
    SM_CYSCREEN = 1
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79

    SRCCOPY = 0x00CC0020

    # Virtual-key names we translate for `key(...)`.
    VK_MAP = {
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
else:
    # Stub constants so ``from ... import *`` doesn't blow up on Linux.
    # Every callable on Linux raises NotImplementedError; env.py + the
    # existing linux dispatch keep the old behaviour.
    user32 = None  # type: ignore[assignment]
    gdi32 = None  # type: ignore[assignment]
    kernel32 = None  # type: ignore[assignment]
    _EnumWindowsProc = None  # type: ignore[assignment]
    VK_MAP: dict[str, int] = {}


def is_available() -> bool:
    """Whether this backend can run in the current process.

    Returns True only on native Windows Python. This is
    checked at import time in the router; callers can
    short-circuit if not available and fall back to the
    Linux dispatch.
    """
    return _IS_WINDOWS


# ---------------------------------------------------------------------------
# Screen metrics
# ---------------------------------------------------------------------------
def virtual_screen_rect() -> tuple[int, int, int, int]:
    """Return (x, y, width, height) of the virtual desktop rect.

    On a single-monitor setup this is (0, 0, W, H). On a
    multi-monitor setup with a monitor to the left of the
    primary, x can be negative (e.g. (-1920, 0, ...) means the
    virtual desktop extends 1920 px to the left of primary).
    Callers that want just the primary monitor should use
    (0, 0, SM_CXSCREEN, SM_CYSCREEN) instead.
    """
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    return (x, y, w, h)


# ---------------------------------------------------------------------------
# Screenshot
# ---------------------------------------------------------------------------
def capture_screenshot(
    *,
    region_x: int | None = None,
    region_y: int | None = None,
    region_width: int | None = None,
    region_height: int | None = None,
) -> bytes:
    """Capture the virtual desktop (or a subregion) and return PNG bytes.

    Uses BitBlt from the desktop DC into a compatible DC. If
    Pillow is available the buffer is transcoded to PNG, else
    BMP bytes are returned (still a valid image, callers can
    detect via magic bytes).
    """
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")

    vx, vy, vw, vh = virtual_screen_rect()
    if region_x is not None and region_y is not None and region_width and region_height:
        x, y = int(region_x), int(region_y)
        w, h = int(region_width), int(region_height)
    else:
        x, y, w, h = vx, vy, vw, vh

    if w <= 0 or h <= 0:
        raise ValueError(f"invalid capture region: {w}x{h}")

    hwnd_desktop = user32.GetDesktopWindow()
    hdc_screen = user32.GetDC(hwnd_desktop)
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, w, h)
    try:
        gdi32.SelectObject(hdc_mem, hbmp)
        ok = gdi32.BitBlt(hdc_mem, 0, 0, w, h, hdc_screen, x, y, SRCCOPY)
        if not ok:
            raise OSError(f"BitBlt failed: LastError={ctypes.get_last_error()}")

        # Convert the HBITMAP to raw BGRA bytes via GetDIBits.
        return _hbitmap_to_png_bytes(hbmp, w, h)
    finally:
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd_desktop, hdc_screen)


def _hbitmap_to_png_bytes(hbmp: int, width: int, height: int) -> bytes:
    """Extract pixels from HBITMAP and encode as PNG (fallback BMP)."""
    # BITMAPINFOHEADER
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
        gdi32.GetDIBits = ctypes.windll.gdi32.GetDIBits
        gdi32.GetDIBits.argtypes = [wt.HDC, wt.HBITMAP, wt.UINT, wt.UINT, ctypes.c_void_p, ctypes.POINTER(BITMAPINFO), wt.UINT]
        gdi32.GetDIBits.restype = ctypes.c_int
        got = gdi32.GetDIBits(hdc_screen, hbmp, 0, height, buf, ctypes.byref(bmi), 0)  # DIB_RGB_COLORS = 0
        if got == 0:
            raise OSError("GetDIBits returned 0")
    finally:
        user32.ReleaseDC(hwnd_desktop, hdc_screen)

    raw = bytes(buf)

    # Try Pillow first (returns a real PNG).
    try:
        from PIL import Image  # type: ignore
        # ctypes buffer is BGRA in top-down order.
        img = Image.frombuffer("RGBA", (width, height), raw, "raw", "BGRA", 0, 1)
        # Alpha from screen DC is typically 0 (BI_RGB doesn't fill it) — drop it.
        img = img.convert("RGB")
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=False)
        return out.getvalue()
    except Exception:
        # Fallback: emit a plain BMP. Callers that want PNG can transcode.
        return _raw_bgra_to_bmp(raw, width, height)


def _raw_bgra_to_bmp(pixels: bytes, width: int, height: int) -> bytes:
    """Wrap raw BGRA pixels in a BITMAPFILEHEADER + BITMAPINFOHEADER."""
    file_size = 14 + 40 + len(pixels)
    header = bytearray()
    # BITMAPFILEHEADER
    header += b"BM"
    header += file_size.to_bytes(4, "little")
    header += b"\x00\x00\x00\x00"
    header += (14 + 40).to_bytes(4, "little")
    # BITMAPINFOHEADER (top-down 32bpp)
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


# ---------------------------------------------------------------------------
# Window listing
# ---------------------------------------------------------------------------
def list_windows(*, visible_only: bool = True) -> list[dict[str, Any]]:
    """Enumerate top-level windows.

    Returns a list of dicts with:
    - ``id``: HWND as a decimal string (matches what ``focus_window`` expects)
    - ``title``: window title
    - ``class``: window class name
    - ``pid``: owning process id
    - ``geometry``: {x, y, width, height}
    - ``visible``: bool
    - ``minimized``: bool
    - ``active``: bool (is this the foreground window)
    """
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")

    fg = user32.GetForegroundWindow()
    results: list[dict[str, Any]] = []

    def _proc(hwnd: int, _lparam: int) -> bool:
        try:
            visible = bool(user32.IsWindowVisible(hwnd))
            if visible_only and not visible:
                return True
            title_len = user32.GetWindowTextLengthW(hwnd)
            title_buf = ctypes.create_unicode_buffer(title_len + 2)
            user32.GetWindowTextW(hwnd, title_buf, title_len + 2)
            title = title_buf.value or ""
            cls_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls_buf, 256)
            cls = cls_buf.value or ""
            # Skip untitled hidden shell windows unless caller explicitly wants them
            if visible_only and not title and cls in {"Progman", "WorkerW", "Shell_TrayWnd", "IME"}:
                return True
            rect = wt.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(rect))
            pid = wt.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            results.append({
                "id": str(hwnd),
                "title": title,
                "class": cls,
                "pid": int(pid.value),
                "geometry": {
                    "x": int(rect.left),
                    "y": int(rect.top),
                    "width": int(rect.right - rect.left),
                    "height": int(rect.bottom - rect.top),
                },
                "visible": visible,
                "minimized": bool(user32.IsIconic(hwnd)),
                "active": hwnd == fg,
            })
        except Exception:
            # One misbehaved window shouldn't kill the enumeration.
            pass
        return True

    cb = _EnumWindowsProc(_proc)
    user32.EnumWindows(cb, 0)
    return results


def get_active_window() -> dict[str, Any] | None:
    """Return the currently-focused window, or None if none."""
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    # Find our own record via list_windows for consistent shape.
    for w in list_windows(visible_only=False):
        if int(w["id"]) == int(hwnd):
            return w
    # Fallback: build a minimal record.
    title_buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title_buf, 512)
    return {"id": str(hwnd), "title": title_buf.value, "active": True}


# ---------------------------------------------------------------------------
# Window discovery: find the "real" main window for a process
# ---------------------------------------------------------------------------
def find_main_window_for_pid(pid: int) -> dict[str, Any] | None:
    """Return the best visible top-level window for a given PID.

    Delphi / Lazarus / LCL apps (Cheat Engine, most RAD-Studio
    installers) expose ``MainWindowHandle`` from Get-Process as
    a hidden ``TApplication`` frame at (-32000, -32000). The
    real user-facing form is a ``TCustomForm`` or ``TFormMain``
    that gets a distinct HWND, and it's the one we need for
    focus/click/screenshot.

    Heuristic: from all visible top-level windows owned by
    ``pid``, prefer the one whose geometry is on-screen AND
    has a non-empty title. If none qualifies, fall back to the
    largest visible one.
    """
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    candidates = [w for w in list_windows(visible_only=True) if w["pid"] == pid]
    if not candidates:
        return None
    # Filter out off-screen windows (Delphi hides the app frame at negative coords).
    on_screen = [
        w for w in candidates
        if w["geometry"]["x"] > -30000 and w["geometry"]["y"] > -30000
        and w["geometry"]["width"] > 20 and w["geometry"]["height"] > 20
    ]
    with_title = [w for w in on_screen if w["title"].strip()]
    if with_title:
        with_title.sort(key=lambda w: -(w["geometry"]["width"] * w["geometry"]["height"]))
        return with_title[0]
    if on_screen:
        on_screen.sort(key=lambda w: -(w["geometry"]["width"] * w["geometry"]["height"]))
        return on_screen[0]
    candidates.sort(key=lambda w: -(w["geometry"]["width"] * w["geometry"]["height"]))
    return candidates[0]


def find_window_by_title(needle: str, *, exact: bool = False) -> dict[str, Any] | None:
    """Find a visible top-level window whose title matches ``needle``.

    Case-insensitive substring match by default. Multi-monitor:
    returns the first match.
    """
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    needle_l = needle.lower()
    for w in list_windows(visible_only=True):
        title = w.get("title") or ""
        if exact and title == needle:
            return w
        if not exact and needle_l in title.lower():
            return w
    return None


# ---------------------------------------------------------------------------
# Window focus
# ---------------------------------------------------------------------------
def focus_window(hwnd: int) -> bool:
    """Bring ``hwnd`` to the foreground, restoring it if minimized.

    Uses the well-known "press ALT once, then SetForegroundWindow"
    trick to release the Windows foreground lock that otherwise
    blocks the transition when the current foreground app is a
    different process (or a different elevation level).
    """
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    hwnd_p = wt.HWND(hwnd)
    if not user32.IsWindow(hwnd_p):
        return False
    # If minimized, restore first.
    if user32.IsIconic(hwnd_p):
        user32.ShowWindow(hwnd_p, SW_RESTORE)
        time.sleep(0.1)
    else:
        user32.ShowWindow(hwnd_p, SW_SHOW)

    # Release foreground lock via ALT tap.
    user32.keybd_event(VK_LMENU, 0, 0, None)
    user32.keybd_event(VK_LMENU, 0, KEYEVENTF_KEYUP, None)
    time.sleep(0.03)

    user32.BringWindowToTop(hwnd_p)
    ok = bool(user32.SetForegroundWindow(hwnd_p))
    time.sleep(0.05)
    return ok or user32.GetForegroundWindow() == hwnd


def move_window(hwnd: int, x: int, y: int, w: int, h: int) -> bool:
    """Move/resize a top-level window and make it visible."""
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    hwnd_p = wt.HWND(hwnd)
    if not user32.IsWindow(hwnd_p):
        return False
    return bool(user32.SetWindowPos(hwnd_p, wt.HWND(0), int(x), int(y), int(w), int(h), SWP_SHOWWINDOW))


# ---------------------------------------------------------------------------
# Mouse input
# ---------------------------------------------------------------------------
def click(x: int, y: int, *, button: str = "left", double: bool = False) -> None:
    """Send a synthetic mouse click at absolute screen coords."""
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    user32.SetCursorPos(int(x), int(y))
    time.sleep(0.03)

    down, up = MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP
    if button == "right":
        down, up = MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP
    elif button == "middle":
        down, up = MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP

    user32.mouse_event(down, 0, 0, 0, None)
    time.sleep(0.03)
    user32.mouse_event(up, 0, 0, 0, None)
    if double:
        time.sleep(0.05)
        user32.mouse_event(down, 0, 0, 0, None)
        time.sleep(0.03)
        user32.mouse_event(up, 0, 0, 0, None)


def mouse_move(x: int, y: int) -> None:
    """Move the cursor to absolute screen coords."""
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    user32.SetCursorPos(int(x), int(y))


def cursor_position() -> tuple[int, int]:
    """Return the current cursor position as (x, y)."""
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return (int(p.x), int(p.y))


# ---------------------------------------------------------------------------
# Keyboard input
# ---------------------------------------------------------------------------
def type_text(text: str, *, delay_ms: int = 5) -> None:
    """Type unicode text into the currently-focused window.

    Uses ``keybd_event`` with ``KEYEVENTF_UNICODE`` so any
    character in the BMP is delivered as a WM_CHAR, bypassing
    layout translation. Characters outside the BMP (emoji etc.)
    are silently dropped by Windows; callers wanting emoji
    should use ``SendInput`` — not implemented here yet.
    """
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    for ch in text:
        code = ord(ch)
        if code > 0xFFFF:
            continue  # non-BMP, drop
        user32.keybd_event(0, code, KEYEVENTF_UNICODE, None)
        user32.keybd_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, None)
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)


def key(name: str, *, modifiers: list[str] | None = None) -> bool:
    """Press a named virtual key with optional modifiers.

    Accepts a single key name like ``"Enter"``, ``"F1"``,
    ``"a"``, ``"escape"``. Modifiers is a list of names from
    {ctrl, shift, alt, win}. Case-insensitive.
    """
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    name_l = (name or "").lower().strip()
    if not name_l:
        return False
    modifiers = [m.lower().strip() for m in (modifiers or [])]

    if name_l in VK_MAP:
        vk = VK_MAP[name_l]
    elif len(name_l) == 1:
        # Letter or digit: use VkKeyScan (returns low byte = VK code, high byte = shift state).
        vks = user32.VkKeyScanW(ctypes.c_wchar(name_l))
        if vks == -1:
            return False
        vk = vks & 0xFF
    else:
        return False

    mod_codes = [VK_MAP[m] for m in modifiers if m in VK_MAP]

    # Press modifiers down
    for mc in mod_codes:
        user32.keybd_event(mc, 0, 0, None)
    user32.keybd_event(vk, 0, 0, None)
    time.sleep(0.03)
    user32.keybd_event(vk, 0, KEYEVENTF_KEYUP, None)
    for mc in reversed(mod_codes):
        user32.keybd_event(mc, 0, KEYEVENTF_KEYUP, None)
    return True


# ---------------------------------------------------------------------------
# Convenience wrappers used by dispatch layer
# ---------------------------------------------------------------------------
def sync_click_and_verify(
    x: int, y: int, *, button: str = "left", double: bool = False,
    focus_hwnd: int | None = None,
) -> dict[str, Any]:
    """Click at (x, y) after optionally focusing a target window.

    Returns a dict with ok/tool/backend keys shaped like the
    Linux input dispatch so the caller sees a uniform envelope.
    """
    if not _IS_WINDOWS:
        return {"ok": False, "error": "windows backend not available"}
    focused = None
    if focus_hwnd is not None:
        focused = focus_window(focus_hwnd)
        time.sleep(0.15)
    click(x, y, button=button, double=double)
    return {
        "ok": True,
        "backend": "windows",
        "tool": "user32",
        "focused_hwnd": focus_hwnd if focused else None,
        "x": int(x),
        "y": int(y),
        "button": button,
        "double": double,
    }
