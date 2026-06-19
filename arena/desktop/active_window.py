"""Active window discovery helper."""
from __future__ import annotations

import os
import shutil

from arena.desktop.exec import _desktop_exec


def _parse_kwin_window_info(text: str) -> dict[str, str]:
    data: dict[str, str] = {}
    for line in (text or "").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


async def _get_active_window() -> dict | None:
    """Get currently active (focused) window info. Used by input guard.

    Tries multiple backends in order of reliability:
    1. KWin DBus queryWindowInfo (KDE Plasma Wayland — most reliable)
    2. xdotool (X11 / XWayland)
    3. kdotool (KDE Wayland fallback)
    4. wmctrl (generic fallback)
    Returns dict with id, title, pid, class or None.
    """
    display_env = f'DISPLAY={os.environ.get("DISPLAY", ":0")}'

    qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
    if qdbus:
        try:
            result = await _desktop_exec(
                f'{qdbus} org.kde.KWin /KWin org.kde.KWin.queryWindowInfo 2>/dev/null',
                timeout=3,
            )
            info = _parse_kwin_window_info(result.get("stdout", "")) if result.get("ok") else {}
            if info.get("caption") or info.get("uuid"):
                geometry = {}
                for key in ("x", "y", "width", "height"):
                    if info.get(key) is not None:
                        try:
                            geometry[key] = int(info[key])
                        except (TypeError, ValueError):
                            geometry[key] = info[key]
                return {
                    "id": info.get("uuid") or info.get("caption") or None,
                    "uuid": info.get("uuid"),
                    "title": info.get("caption", ""),
                    "pid": info.get("pid") or None,
                    "class": info.get("resourceClass", ""),
                    "resource_name": info.get("resourceName", ""),
                    "desktop_file": info.get("desktopFile", ""),
                    "geometry": geometry or None,
                    "active": True,
                    "backend": "kwin_dbus",
                }
        except Exception:
            pass

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
