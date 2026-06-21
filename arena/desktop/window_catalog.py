"""Desktop window listing, display annotation, and candidate matching helpers."""
from __future__ import annotations

import os
import shlex
import shutil
from typing import Any

from arena.desktop.displays import get_displays
from arena.desktop.text_matching import coerce_geometry, normalize_text, point_in_geometry


def _overlap_area(a: dict[str, int] | None, b: dict[str, int] | None) -> int:
    if not a or not b:
        return 0
    left = max(a["x"], b["x"])
    top = max(a["y"], b["y"])
    right = min(a["x"] + a["width"], b["x"] + b["width"])
    bottom = min(a["y"] + a["height"], b["y"] + b["height"])
    return max(0, right - left) * max(0, bottom - top)



def annotate_windows_with_displays(windows: list[dict[str, Any]], displays: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for window in windows:
        geometry = coerce_geometry(window.get("geometry"))
        window["geometry"] = geometry
        center = None
        if geometry:
            center = {"x": geometry["x"] + geometry["width"] // 2, "y": geometry["y"] + geometry["height"] // 2}
        best = None
        best_area = -1
        for display in displays:
            display_geom = coerce_geometry(display.get("geometry"))
            area = _overlap_area(geometry, display_geom)
            if area > best_area:
                best_area = area
                best = display
            if center and point_in_geometry(center, display_geom):
                best = display
                break
        window["display"] = None if not best else {"name": best.get("name"), "id": best.get("id"), "active": best.get("active", False)}
    return windows



def _window_matches(window: dict[str, Any], *, title: str = "", class_contains: str = "", desktop_file: str = "", resource_name: str = "", pid: int | None = None, display: str = "", active_only: bool = False) -> bool:
    if active_only and not window.get("active"):
        return False
    if pid is not None and int(window.get("pid") or -1) != int(pid):
        return False
    title_q = normalize_text(title)
    if title_q and title_q not in normalize_text(window.get("title", "")):
        return False
    class_q = normalize_text(class_contains)
    if class_q and class_q not in normalize_text(window.get("resource_class", window.get("class", ""))):
        return False
    df_q = normalize_text(desktop_file)
    if df_q and df_q not in normalize_text(window.get("desktop_file", "")):
        return False
    rn_q = normalize_text(resource_name)
    if rn_q and rn_q not in normalize_text(window.get("resource_name", "")):
        return False
    display_q = normalize_text(display)
    display_name = ((window.get("display") or {}).get("name") or "")
    if display_q and display_q not in normalize_text(display_name):
        return False
    return True



def window_candidates(windows: list[dict[str, Any]], **filters: Any) -> list[dict[str, Any]]:
    title_q = normalize_text(filters.get("title", ""))
    class_q = normalize_text(filters.get("class_contains", ""))
    scored = []
    for window in windows:
        if not _window_matches(window, **filters):
            continue
        score = 0.0
        if window.get("active"):
            score += 0.02
        window_title = normalize_text(window.get("title", ""))
        window_class = normalize_text(window.get("resource_class", window.get("class", "")))
        if title_q:
            if window_title == title_q:
                score += 1.0
            elif title_q in window_title:
                score += 0.8
        if class_q:
            if window_class == class_q:
                score += 0.5
            elif class_q in window_class:
                score += 0.35
        if filters.get("pid") is not None:
            score += 0.2
        if filters.get("display"):
            score += 0.1
        scored.append((score, window))
    scored.sort(key=lambda item: (item[0], bool(item[1].get("active")), len(str(item[1].get("title", "")))), reverse=True)
    return [window for _, window in scored]


async def list_desktop_windows(*, desktop_exec, detect_env, kwin_windows_via_script) -> dict[str, Any]:
    env = detect_env()
    display_env = f'DISPLAY={os.environ.get("DISPLAY", ":0")}'
    attempts = []
    displays = []
    try:
        displays = (await get_displays(desktop_exec=desktop_exec)).get("displays", [])
    except Exception:
        displays = []
    kwin = await kwin_windows_via_script()
    if kwin and kwin.get("ok"):
        windows = annotate_windows_with_displays(list(kwin.get("windows") or []), displays)
        return {**kwin, "windows": windows, "tool": kwin.get("backend", "kwin_script"), "attempts": attempts, "displays": displays}
    if kwin:
        attempts.append({"tool": "kwin_script", "ok": False, "error": kwin.get("error")})
    if shutil.which("wmctrl"):
        result = await desktop_exec(f'{display_env} wmctrl -l -p -G 2>/dev/null', timeout=5)
        attempts.append({"tool": "wmctrl", "ok": result.get("ok"), "stderr": result.get("stderr", "")[:200]})
        if result.get("ok") and result.get("stdout", "").strip():
            windows = []
            for line in result["stdout"].strip().split("\n"):
                parts = line.split(None, 8)
                if len(parts) >= 8:
                    windows.append({"id": parts[0], "desktop": parts[1], "pid": parts[2], "geometry": {"x": int(parts[3]), "y": int(parts[4]), "width": int(parts[5]), "height": int(parts[6])}, "host": parts[7], "title": parts[8] if len(parts) >= 9 else ""})
            windows = annotate_windows_with_displays(windows, displays)
            return {"ok": True, "count": len(windows), "windows": windows, "tool": "wmctrl", "attempts": attempts, "displays": displays}
    if env.get("has_xdotool"):
        result = await desktop_exec(f'{display_env} xdotool search --onlyvisible --name "" 2>/dev/null', timeout=5)
        attempts.append({"tool": "xdotool", "ok": result.get("ok"), "stderr": result.get("stderr", "")[:200]})
        if result.get("ok") and result.get("stdout", "").strip():
            windows = []
            for wid in result["stdout"].strip().split("\n")[:50]:
                wid_q = shlex.quote(wid)
                geom = await desktop_exec(f'{display_env} xdotool getwindowgeometry {wid_q} 2>/dev/null', timeout=3)
                name = await desktop_exec(f'{display_env} xdotool getwindowname {wid_q} 2>/dev/null', timeout=3)
                pid = await desktop_exec(f'{display_env} xdotool getwindowpid {wid_q} 2>/dev/null', timeout=3)
                windows.append({"id": wid, "title": name.get("stdout", "").strip() if name.get("ok") else "", "pid": pid.get("stdout", "").strip() if pid.get("ok") else None, "geometry": coerce_geometry(geom.get("stdout", ""))})
            windows = annotate_windows_with_displays(windows, displays)
            return {"ok": True, "count": len(windows), "windows": windows, "tool": "xdotool", "attempts": attempts, "displays": displays}
    return {"ok": True, "count": 0, "windows": [], "tool": "none", "attempts": attempts, "displays": displays}


__all__ = ["annotate_windows_with_displays", "list_desktop_windows", "window_candidates"]
