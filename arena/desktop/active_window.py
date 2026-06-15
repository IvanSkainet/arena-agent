"""Active window discovery helper."""
from __future__ import annotations

import os
import shutil

from arena.desktop.exec import _desktop_exec


async def _get_active_window() -> dict | None:
    """Get currently active (focused) window info. Used by input guard.

    Tries multiple backends in order of reliability:
    1. KWin DBus (KDE Plasma Wayland — most reliable)
    2. xdotool (X11 / XWayland)
    3. kdotool (KDE Wayland fallback)
    4. wmctrl (generic fallback)
    Returns dict with id, title, pid, class or None.
    """
    display_env = f'DISPLAY={os.environ.get("DISPLAY", ":0")}'

    # Strategy 0: KWin DBus (KDE Plasma Wayland — native, most reliable)
    # Uses org.kde.KWin to get active window caption and ID
    if shutil.which("dbus-send") or shutil.which("qdbus") or shutil.which("qdbus6"):
        try:
            # Try qdbus6 first (KDE Plasma 6)
            qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
            if qdbus:
                # Get active window caption
                result = await _desktop_exec(
                    f'{qdbus} org.kde.KWin /KWin org.kde.KWin.getActiveOutputName 2>/dev/null',
                    timeout=2)
                # Get active window info via KWin scripting
                result = await _desktop_exec(
                    f'{qdbus} org.kde.KWin /KWin supportInformation 2>/dev/null | '
                    f'grep -A2 "Active window"',
                    timeout=3)
                # Simpler approach: get active window via kscreen/kwin
                result = await _desktop_exec(
                    f'dbus-send --session --dest=org.kde.KWin --type=method_call '
                    f'--print-reply /KWin org.kde.KWin.getActiveWindowId 2>/dev/null',
                    timeout=3)
                if result["ok"] and result["stdout"].strip():
                    # Parse int32 from dbus reply
                    import re as _re
                    match = _re.search(r'int32\s+(\d+)|int64\s+(\d+)', result["stdout"])
                    if match:
                        wid = match.group(1) or match.group(2)
                        if wid and wid != "0":
                            # Get window caption
                            caption_r = await _desktop_exec(
                                f'dbus-send --session --dest=org.kde.KWin --type=method_call '
                                f'--print-reply /KWin org.kde.KWin.getWindowCaption int32:{wid} 2>/dev/null',
                                timeout=2)
                            title = ""
                            if caption_r["ok"] and caption_r["stdout"].strip():
                                # Parse string from dbus reply: string "caption"
                                cap_match = _re.search(r'string\s+"(.+)"', caption_r["stdout"])
                                if cap_match:
                                    title = cap_match.group(1)
                            return {
                                "id": wid,
                                "title": title,
                                "backend": "kwin_dbus",
                            }
        except Exception:
            pass  # Fall through to other strategies

    # Strategy 1: xdotool getactivewindow (X11 / XWayland)
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
                "title": name_r.get("stdout", "").strip() if name_r["ok"] else "",
                "pid": pid_r.get("stdout", "").strip() if pid_r["ok"] else None,
                "class": cls_r.get("stdout", "").strip() if cls_r["ok"] else "",
                "geometry": geom_r.get("stdout", "").strip() if geom_r["ok"] else "",
                "backend": "xdotool",
            }

    # Strategy 2: kdotool (KDE Plasma Wayland)
    if shutil.which("kdotool"):
        result = await _desktop_exec(
            'kdotool search --active 2>/dev/null || '
            'kdotool search --onlyvisible --active 2>/dev/null', timeout=3)
        if result["ok"] and result["stdout"].strip():
            wid = result["stdout"].strip().split("\n")[0]
            return {
                "id": wid,
                "title": "",  # kdotool doesn't easily give title
                "backend": "kdotool",
            }

    # Strategy 3: wmctrl active window (reads * marker)
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

