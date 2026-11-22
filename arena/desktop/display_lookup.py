"""Where the list of displays comes from: user32 on Windows, the Linux tools elsewhere (#514)."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from arena.desktop import displays as _linux_tools
from arena.desktop.displays import DesktopExec

_WIN32_TOOL = "user32.EnumDisplayMonitors"


def _answer(outputs: list[dict[str, Any]], attempt: dict[str, Any]) -> dict[str, Any]:
    active_output = next((output["name"] for output in outputs if output["active"]), None)
    return {
        "ok": bool(attempt["ok"]),
        "backend": "win32",
        "active_output": active_output,
        "count": len(outputs),
        "displays": outputs,
        "attempts": [attempt],
    }


async def _win32_displays() -> dict[str, Any]:
    """Ask user32: Windows has neither kscreen-doctor nor xrandr."""
    from arena.desktop.backends import windows_displays

    try:
        outputs = await asyncio.get_running_loop().run_in_executor(None, windows_displays.list_displays)
    except OSError as exc:
        # Not an empty list: "this machine has no displays" was the wrong answer #514 is about.
        return {**_answer([], {"tool": _WIN32_TOOL, "ok": False, "error": str(exc)}), "error": str(exc)}
    return _answer(outputs, {"tool": _WIN32_TOOL, "ok": True})


async def get_displays(*, desktop_exec: DesktopExec, env: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """List the displays of the desktop that `env` describes."""
    if env is not None and env.get("has_win32_windows"):
        return await _win32_displays()
    return await _linux_tools.get_displays(desktop_exec=desktop_exec)
