"""Active window discovery helper."""
from __future__ import annotations

import os
import shutil
import sys

from arena.desktop.exec import _desktop_exec
from arena.desktop.kwin import _kwin_windows_via_script

# v4.81.1: module-level flag that gates the native win32 shortcut.
# Kept mutable so pre-existing KWin/xdotool tests can flip it off
# on a Windows CI runner without touching sys.platform.
_USE_WIN32_ACTIVE_WINDOW = sys.platform == "win32"


async def _get_active_window() -> dict | None:
    """Get currently active (focused) window info. Used by input guard.

    Backend order:
    1. Windows native (user32.GetForegroundWindow) if on Windows
    2. Native KWin journal-backed window list (preferred on KDE/Wayland)
    3. xdotool (X11 / XWayland)
    4. kdotool (KDE Wayland fallback)
    5. wmctrl (generic fallback)

    Returns dict with id, title, pid, class or None.
    """
    # v4.81.0: Windows native path (no subprocess).
    # v4.81.1: expose the gate as ``_USE_WIN32_ACTIVE_WINDOW`` so
    # legacy KWin/xdotool unit tests can force the Linux branch on a
    # Windows CI runner via ``monkeypatch.setattr``.
    if _USE_WIN32_ACTIVE_WINDOW:  # pragma: no cover
        try:
            from arena.desktop.backends import windows as _win
            w = _win.get_active_window()
            if w:
                w.setdefault("backend", "windows_user32")
                return w
        except Exception:
            pass
        return None

    display_env = f'DISPLAY={os.environ.get("DISPLAY", ":0")}'

    kwin_list = await _kwin_windows_via_script()
    if kwin_list and kwin_list.get("ok"):
        for win in kwin_list.get("windows") or []:
            if win.get("active"):
                return {
                    "id": win.get("id"),
                    "uuid": win.get("internal_id"),
                    "title": win.get("title", ""),
                    "pid": win.get("pid"),
                    "class": win.get("resource_class", ""),
                    "resource_name": win.get("resource_name", ""),
                    "desktop_file": win.get("desktop_file", ""),
                    "geometry": win.get("geometry"),
                    "active": True,
                    "backend": "kwin_journal",
                }

    if shutil.which("xdotool"):
        result = await _desktop_exec(
            f'{display_env} xdotool getactivewindow 2>/dev/null', timeout=3)
        if result["ok"] and result["stdout"].strip():
            wid = result["stdout"].strip().split("\n")[0]
            name_r = await _desktop_exec(
                f'{display_env} xdotool getwindowname {wid} 2>/dev/null', timeout=2)
            pid_r = await _desktop_exec(
                f'{display_env} xdotool getwindowpid {wid} 2>/dev/null', timeout=2)
            cls_r = await _desktop_exec(
                f'{display_env} xdotool getwindowclassname {wid} 2>/dev/null || '
                f'xprop -id {wid} WM_CLASS 2>/dev/null | cut -d\\" -f2', timeout=2)
            geom_r = await _desktop_exec(
                f'{display_env} xdotool getwindowgeometry {wid} 2>/dev/null', timeout=2)
            return {
                "id": wid,
                "title": name_r.get("stdout", "").strip() if name_r.get("ok") else "",
                "pid": pid_r.get("stdout", "").strip() if pid_r.get("ok") else None,
                "class": cls_r.get("stdout", "").strip() if cls_r.get("ok") else "",
                "geometry": geom_r.get("stdout", "").strip() if geom_r.get("ok") else "",
                "backend": "xdotool",
            }

    if shutil.which("kdotool"):
        result = await _desktop_exec(
            'kdotool search --active 2>/dev/null || '
            'kdotool search --onlyvisible --active 2>/dev/null', timeout=3)
        if result["ok"] and result["stdout"].strip():
            wid = result["stdout"].strip().split("\n")[0]
            return {
                "id": wid,
                "title": "",
                "backend": "kdotool",
            }

    if shutil.which("wmctrl"):
        result = await _desktop_exec(
            f'{display_env} wmctrl -l -p 2>/dev/null', timeout=3)
        if result["ok"]:
            for line in result["stdout"].strip().split("\n"):
                if "*" in line:
                    parts = line.split(None, 5)
                    if len(parts) >= 5:
                        return {
                            "id": parts[0],
                            "desktop": parts[1],
                            "pid": parts[2],
                            "host": parts[3],
                            "title": parts[4] if len(parts) == 5 else " ".join(parts[4:]),
                            "active": True,
                            "backend": "wmctrl",
                        }

    return None
