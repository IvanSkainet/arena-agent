"""Desktop window focus helpers."""
from __future__ import annotations

import asyncio
import os
import shlex
import shutil
from collections.abc import Awaitable, Callable
from typing import Any

DesktopExec = Callable[[str, float], Awaitable[dict[str, Any]]]
DetectEnv = Callable[[], dict[str, Any]]
ActiveWindowFn = Callable[[], Awaitable[dict[str, Any] | None]]


async def focus_window(
    *,
    window_id: str | None = None,
    title_contains: str | None = None,
    target_title: str | None = None,
    verify: bool = True,
    verify_timeout_ms: int = 1500,
    desktop_exec: DesktopExec,
    detect_env: DetectEnv,
    get_active_window: ActiveWindowFn,
    kwin_focus_window=None,
) -> dict[str, Any]:
    """Focus a desktop window by ID or title and optionally verify it."""
    active_before = await get_active_window()
    env = detect_env()
    display_env = f'DISPLAY={os.environ.get("DISPLAY", ":0")}'

    target_id = window_id
    target_title = target_title or ""

    if not target_id and title_contains:
        if shutil.which("wmctrl"):
            result = await desktop_exec(f'{display_env} wmctrl -l -p 2>/dev/null', timeout=5)
            if result.get("ok"):
                for line in result.get("stdout", "").strip().split("\n"):
                    parts = line.split(None, 5)
                    if len(parts) >= 5:
                        title = parts[4] if len(parts) == 5 else " ".join(parts[4:])
                        if title_contains.lower() in title.lower():
                            target_id = parts[0]
                            target_title = title
                            break
        if not target_id and env.get("has_xdotool"):
            result = await desktop_exec(
                f'{display_env} xdotool search --name {shlex.quote(title_contains)} 2>/dev/null',
                timeout=5,
            )
            if result.get("ok") and result.get("stdout", "").strip():
                target_id = result["stdout"].strip().split("\n")[0]

    if not target_id:
        return {
            "ok": False,
            "error": "window_not_found",
            "message": f"Could not find window matching: {title_contains or window_id}",
            "active_before": active_before,
            "status": 404,
        }

    focus_ok = False
    focus_tool = "none"

    # Strategy A: native non-interactive KWin focus helper.
    if not focus_ok and kwin_focus_window is not None:
        try:
            result = await kwin_focus_window(str(target_id), desktop_exec=desktop_exec)
            if result.get("ok"):
                focus_ok = True
                focus_tool = result.get("backend", "kwin_focus_script")
        except Exception:
            pass

    # Strategy B: KWin DBus for numeric ids.
    if not focus_ok:
        try:
            wid_int = int(target_id, 0)
            result = await desktop_exec(
                f'dbus-send --session --dest=org.kde.KWin --type=method_call '
                f'/KWin org.kde.KWin.setActiveWindow int32:{wid_int} 2>/dev/null',
                timeout=5,
            )
            if result.get("ok") and result.get("exit_code") == 0:
                focus_ok = True
                focus_tool = "kwin_dbus"
        except (ValueError, Exception):
            pass

    if not focus_ok and shutil.which("wmctrl"):
        result = await desktop_exec(f'{display_env} wmctrl -i -a {target_id} 2>/dev/null', timeout=5)
        if result.get("ok") and result.get("exit_code") == 0:
            focus_ok = True
            focus_tool = "wmctrl"

    if not focus_ok and env.get("has_xdotool"):
        result = await desktop_exec(f'{display_env} xdotool windowactivate --sync {target_id} 2>/dev/null', timeout=5)
        if result.get("ok") and result.get("exit_code") == 0:
            focus_ok = True
            focus_tool = "xdotool"

    if not focus_ok and shutil.which("kdotool"):
        result = await desktop_exec(f'kdotool activate {target_id} 2>/dev/null', timeout=5)
        if result.get("ok") and result.get("exit_code") == 0:
            focus_ok = True
            focus_tool = "kdotool"

    # Keep historical last-resort qdbus placeholder behavior (best-effort no-op).
    if not focus_ok:
        qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
        if qdbus:
            try:
                int(target_id, 0)
                await desktop_exec(
                    f'{qdbus} org.kde.KWin /Scripting org.kde.kwin.Scripting.loadScript eval 2>/dev/null',
                    timeout=5,
                )
            except (ValueError, Exception):
                pass

    if not focus_ok:
        return {
            "ok": False,
            "error": "focus_failed",
            "message": "All focus methods failed",
            "target_id": target_id,
            "active_before": active_before,
            "backend": env.get("session_type", "unknown"),
            "status": 500,
        }

    active_after = None
    verify_ok = False
    if verify:
        await asyncio.sleep(verify_timeout_ms / 1000.0)
        active_after = await get_active_window()
        if active_after:
            if (
                active_after.get("id") == target_id
                or (target_title and target_title.lower() in active_after.get("title", "").lower())
                or (title_contains and title_contains.lower() in active_after.get("title", "").lower())
            ):
                verify_ok = True
    else:
        verify_ok = True

    return {
        "ok": verify_ok,
        "focused": focus_ok,
        "verified": verify_ok if verify else None,
        "target_id": target_id,
        "target_title": target_title,
        "active_before": active_before,
        "active_after": active_after,
        "tool": focus_tool,
        "backend": env.get("session_type", "unknown"),
    }
