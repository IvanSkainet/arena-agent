"""Desktop window action execution helpers."""
from __future__ import annotations

import asyncio
import os
import shlex
import shutil
from typing import Any

from arena.desktop.kwin_window_action import kwin_window_action_via_script
from arena.desktop.window_catalog import find_window_by_id, list_desktop_windows


async def perform_window_action(
    action: str,
    *,
    target_id: str,
    title_contains: str = "",
    target_title: str = "",
    x=None,
    y=None,
    width=None,
    height=None,
    verify: bool = True,
    verify_timeout_ms: int = 1000,
    desktop_exec,
    detect_env,
    kwin_windows_via_script,
) -> dict[str, Any]:
    action = str(action or "").strip().lower()
    before_listing = await list_desktop_windows(desktop_exec=desktop_exec, detect_env=detect_env, kwin_windows_via_script=kwin_windows_via_script)
    before = find_window_by_id(list(before_listing.get("windows") or []), target_id)
    env = detect_env()
    display_env = f'DISPLAY={os.environ.get("DISPLAY", ":0")}'
    backend = "none"
    backend_detail = None

    kwin_like_target = str(target_id).startswith("{") and str(target_id).endswith("}")
    if kwin_like_target or env.get("session_type") == "wayland":
        backend_detail = await kwin_window_action_via_script(action, target_id, x=x, y=y, width=width, height=height, desktop_exec=desktop_exec)
        if backend_detail.get("ok"):
            backend = backend_detail.get("backend", "kwin_window_action")

    if backend == "none" and shutil.which("wmctrl"):
        cmd = _wmctrl_command(action, target_id, before, x=x, y=y, width=width, height=height, display_env=display_env)
        if cmd:
            result = await desktop_exec(cmd, timeout=5)
            if result.get("ok") and result.get("exit_code") == 0:
                backend = "wmctrl"
                backend_detail = result

    if backend == "none" and env.get("has_xdotool"):
        cmd = _xdotool_command(action, target_id, before, x=x, y=y, width=width, height=height, display_env=display_env)
        if cmd:
            result = await desktop_exec(cmd, timeout=5)
            if result.get("ok") and result.get("exit_code") == 0:
                backend = "xdotool"
                backend_detail = result

    if backend == "none":
        return {"ok": False, "error": "window_action_failed", "message": f"No backend could execute action: {action}", "target_id": target_id, "action": action, "before": before, "status": 500}

    after = None
    verified = None
    if verify:
        await asyncio.sleep(max(0, int(verify_timeout_ms or 1000)) / 1000.0)
        after_listing = await list_desktop_windows(desktop_exec=desktop_exec, detect_env=detect_env, kwin_windows_via_script=kwin_windows_via_script)
        after = find_window_by_id(list(after_listing.get("windows") or []), target_id)
        verified = _verify_action(action, before, after, x=x, y=y, width=width, height=height)
    return {"ok": bool(backend) and (verified is not False), "action": action, "target_id": target_id, "title_contains": title_contains, "target_title": target_title, "tool": backend, "before": before, "after": after, "verified": verified, "backend_detail": backend_detail}



def _verify_action(action: str, before: dict[str, Any] | None, after: dict[str, Any] | None, *, x=None, y=None, width=None, height=None) -> bool:
    if not after:
        return False
    if action == "minimize":
        return after.get("minimized") is True
    if action == "restore":
        return not after.get("minimized", False) and not after.get("full_screen", False)
    if action == "fullscreen":
        return after.get("full_screen") is True
    if action == "unfullscreen":
        return after.get("full_screen") is False
    geometry = after.get("geometry") or {}
    checks = []
    if x is not None:
        checks.append(int(geometry.get("x", -1)) == int(x))
    if y is not None:
        checks.append(int(geometry.get("y", -1)) == int(y))
    if width is not None:
        checks.append(int(geometry.get("width", -1)) == int(width))
    if height is not None:
        checks.append(int(geometry.get("height", -1)) == int(height))
    return all(checks) if checks else after != before



def _wmctrl_command(action: str, target_id: str, before: dict[str, Any] | None, *, x=None, y=None, width=None, height=None, display_env: str) -> str | None:
    if action == "minimize":
        return f'{display_env} wmctrl -i -r {target_id} -b add,hidden 2>/dev/null'
    if action == "restore":
        return f'{display_env} wmctrl -i -r {target_id} -b remove,hidden,fullscreen,maximized_vert,maximized_horz 2>/dev/null'
    if action == "fullscreen":
        return f'{display_env} wmctrl -i -r {target_id} -b add,fullscreen 2>/dev/null'
    if action == "unfullscreen":
        return f'{display_env} wmctrl -i -r {target_id} -b remove,fullscreen 2>/dev/null'
    if action in {"move", "resize", "move_resize"}:
        g = (before or {}).get("geometry") or {}
        nx = int(g.get("x", 0) if x is None else x)
        ny = int(g.get("y", 0) if y is None else y)
        nw = int(g.get("width", 100) if width is None else width)
        nh = int(g.get("height", 100) if height is None else height)
        return f'{display_env} wmctrl -i -r {target_id} -e 0,{nx},{ny},{nw},{nh} 2>/dev/null'
    return None



def _xdotool_command(action: str, target_id: str, before: dict[str, Any] | None, *, x=None, y=None, width=None, height=None, display_env: str) -> str | None:
    wid = shlex.quote(str(target_id))
    if action == "minimize":
        return f'{display_env} xdotool windowminimize {wid} 2>/dev/null'
    if action == "restore":
        return f'{display_env} xdotool windowmap {wid} 2>/dev/null'
    if action in {"move", "resize", "move_resize"}:
        g = (before or {}).get("geometry") or {}
        nx = int(g.get("x", 0) if x is None else x)
        ny = int(g.get("y", 0) if y is None else y)
        nw = int(g.get("width", 100) if width is None else width)
        nh = int(g.get("height", 100) if height is None else height)
        cmds = []
        if action in {"move", "move_resize"}:
            cmds.append(f'{display_env} xdotool windowmove {wid} {nx} {ny}')
        if action in {"resize", "move_resize"}:
            cmds.append(f'{display_env} xdotool windowsize {wid} {nw} {nh}')
        return " && ".join(cmds)
    return None


__all__ = ["perform_window_action"]
