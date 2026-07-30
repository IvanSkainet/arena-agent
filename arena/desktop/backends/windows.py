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

v4.81.1: the ctypes signature declarations and the BMP helpers
were moved out into ``_win32_api.py`` so this file stays under
the 600-line "modular runtime" threshold enforced by
``tests/test_architecture_boundaries.py``.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
import time
from typing import Any

from arena.desktop.backends import _win32_api as _api

_IS_WINDOWS = sys.platform == "win32"

# Re-exported for callers/tests that historically imported these
# names directly from this module.
user32 = _api.user32
gdi32 = _api.gdi32
kernel32 = _api.kernel32
dwmapi = _api.dwmapi
VK_MAP = _api.VK_MAP

SW_RESTORE = _api.SW_RESTORE
SW_SHOW = _api.SW_SHOW
SWP_SHOWWINDOW = _api.SWP_SHOWWINDOW
MOUSEEVENTF_LEFTDOWN = _api.MOUSEEVENTF_LEFTDOWN
MOUSEEVENTF_LEFTUP = _api.MOUSEEVENTF_LEFTUP
MOUSEEVENTF_RIGHTDOWN = _api.MOUSEEVENTF_RIGHTDOWN
MOUSEEVENTF_RIGHTUP = _api.MOUSEEVENTF_RIGHTUP
MOUSEEVENTF_MIDDLEDOWN = _api.MOUSEEVENTF_MIDDLEDOWN
MOUSEEVENTF_MIDDLEUP = _api.MOUSEEVENTF_MIDDLEUP
KEYEVENTF_KEYUP = _api.KEYEVENTF_KEYUP
KEYEVENTF_UNICODE = _api.KEYEVENTF_UNICODE
VK_LMENU = _api.VK_LMENU
SM_XVIRTUALSCREEN = _api.SM_XVIRTUALSCREEN
SM_YVIRTUALSCREEN = _api.SM_YVIRTUALSCREEN
SM_CXVIRTUALSCREEN = _api.SM_CXVIRTUALSCREEN
SM_CYVIRTUALSCREEN = _api.SM_CYVIRTUALSCREEN
SRCCOPY = _api.SRCCOPY

# Backwards-compat re-exports for the pre-v4.81.1 layout, where the
# BMP fallback encoder lived in this module. Some tests import them
# from here directly.
_hbitmap_to_png_bytes = _api.hbitmap_to_png_bytes
_raw_bgra_to_bmp = _api.raw_bgra_to_bmp


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
    """Return (x, y, width, height) of the virtual desktop rect."""
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
        return _api.hbitmap_to_png_bytes(hbmp, w, h)
    finally:
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd_desktop, hdc_screen)


DWMWA_EXTENDED_FRAME_BOUNDS = 9


def _rect_to_geometry(rect: wt.RECT) -> dict[str, int]:
    return {
        "x": int(rect.left),
        "y": int(rect.top),
        "width": int(rect.right - rect.left),
        "height": int(rect.bottom - rect.top),
    }


def _best_window_geometry(hwnd: int) -> dict[str, int]:
    """Return the most useful top-level window geometry.

    ``GetWindowRect`` can be misleading for some Windows/custom-toolkit
    windows after restore (live Cheat Engine validation showed a visible
    owner window at x=20,y=20,width=985,height=0). DWM extended frame
    bounds are the better visual rectangle when available, so prefer them
    whenever they produce a positive area.
    """
    rect = wt.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    geom = _rect_to_geometry(rect)
    if dwmapi is not None:
        try:
            dwm_rect = wt.RECT()
            hr = dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), DWMWA_EXTENDED_FRAME_BOUNDS, ctypes.byref(dwm_rect), ctypes.sizeof(dwm_rect))
            dwm_geom = _rect_to_geometry(dwm_rect)
            if hr == 0 and dwm_geom["width"] > 0 and dwm_geom["height"] > 0:
                return dwm_geom
        except Exception:
            pass
    return geom


# ---------------------------------------------------------------------------
# Window listing
# ---------------------------------------------------------------------------
def list_windows(*, visible_only: bool = True) -> list[dict[str, Any]]:
    """Enumerate top-level windows.

    Returns a list of dicts with:
    - ``id``: HWND as a decimal string
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
            if visible_only and not title and cls in {"Progman", "WorkerW", "Shell_TrayWnd", "IME"}:
                return True
            geometry = _best_window_geometry(hwnd)
            pid = wt.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            results.append({
                "id": str(hwnd),
                "title": title,
                "class": cls,
                "pid": int(pid.value),
                "geometry": geometry,
                "visible": visible,
                "minimized": bool(user32.IsIconic(hwnd)),
                "active": hwnd == fg,
            })
        except Exception:
            pass
        return True

    cb = _api.EnumWindowsProc(_proc)
    user32.EnumWindows(cb, 0)
    return results


def get_active_window() -> dict[str, Any] | None:
    """Return the currently-focused window, or None if none."""
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return None
    for w in list_windows(visible_only=False):
        if int(w["id"]) == int(hwnd):
            return w
    title_buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title_buf, 512)
    return {"id": str(hwnd), "title": title_buf.value, "active": True}


# ---------------------------------------------------------------------------
# Window discovery
# ---------------------------------------------------------------------------
def find_main_window_for_pid(pid: int) -> dict[str, Any] | None:
    """Return the best visible top-level window for a given PID.

    Delphi / Lazarus / LCL apps (Cheat Engine, most RAD-Studio
    installers) expose ``MainWindowHandle`` from Get-Process as
    a hidden ``TApplication`` frame at (-32000, -32000). The
    real user-facing form is a ``TCustomForm`` or ``TFormMain``
    that gets a distinct HWND.

    Heuristic: from all visible top-level windows owned by
    ``pid``, prefer the one whose geometry is on-screen AND
    has a non-empty title. Fall back to largest visible one.
    """
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    candidates = [w for w in list_windows(visible_only=True) if w["pid"] == pid]
    if not candidates:
        return None
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
    """Find a visible top-level window whose title matches ``needle``."""
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
# Window focus / geometry
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
    if user32.IsIconic(hwnd_p):
        user32.ShowWindow(hwnd_p, SW_RESTORE)
        time.sleep(0.1)
    else:
        user32.ShowWindow(hwnd_p, SW_SHOW)

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
    """Type unicode text into the currently-focused window."""
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    for ch in text:
        code = ord(ch)
        if code > 0xFFFF:
            continue
        user32.keybd_event(0, code, KEYEVENTF_UNICODE, None)
        user32.keybd_event(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, None)
        if delay_ms > 0:
            time.sleep(delay_ms / 1000.0)


def key(name: str, *, modifiers: list[str] | None = None) -> bool:
    """Press a named virtual key with optional modifiers."""
    if not _IS_WINDOWS:
        raise NotImplementedError("windows backend not available on this platform")
    name_l = (name or "").lower().strip()
    if not name_l:
        return False
    modifiers = [m.lower().strip() for m in (modifiers or [])]

    if name_l in VK_MAP:
        vk = VK_MAP[name_l]
    elif len(name_l) == 1:
        vks = user32.VkKeyScanW(ctypes.c_wchar(name_l))
        if vks == -1:
            return False
        vk = vks & 0xFF
    else:
        return False

    mod_codes = [VK_MAP[m] for m in modifiers if m in VK_MAP]
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
    """Click at (x, y) after optionally focusing a target window."""
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
