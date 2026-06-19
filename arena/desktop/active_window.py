"""Active window discovery helper."""
from __future__ import annotations

import os
import shutil

from arena.desktop.exec import _desktop_exec
from arena.desktop.kwin import _kwin_windows_via_script


async def _get_active_window() -> dict | None:
    """Get currently active (focused) window info. Used by input guard.

    Backend order is chosen to avoid interactive desktop prompts on KDE/Wayland:
    1. Native KWin journal-backed window list (preferred on KDE/Wayland)
    2. xdotool (X11 / XWayland)
    3. kdotool (KDE Wayland fallback)
    4. wmctrl (generic fallback)

    Returns dict with id, title, pid, class or None.
    """
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
