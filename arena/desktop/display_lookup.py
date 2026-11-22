"""Where the list of displays comes from: user32 on Windows, the Linux tools elsewhere (#514)."""
from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from arena.desktop import displays as _linux_tools
from arena.desktop.displays import DesktopExec
from arena.desktop.text_matching import coerce_geometry

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


def _overlap(window: dict[str, int], display: dict[str, int]) -> int:
    """Return the area the two rectangles share, in pixels."""
    width = min(window["x"] + window["width"], display["x"] + display["width"]) - max(window["x"], display["x"])
    height = min(window["y"] + window["height"], display["y"] + display["height"]) - max(window["y"], display["y"])
    return max(0, width) * max(0, height)


def _showing(geometry: dict[str, int], displays: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return a reference to the display that shows most of the rectangle, or None if none shows any."""
    best = max(displays, key=lambda display: _overlap(geometry, display["geometry"]), default=None)
    # A minimised window is parked far off-screen and is on no display.
    if best is None or not _overlap(geometry, best["geometry"]):
        return None
    return {"name": best["name"], "id": best["id"], "active": best["active"]}


def attribute_windows(windows: list[dict[str, Any]], displays: list[dict[str, Any]]) -> None:
    """Name, on each window record, the display that shows most of it."""
    for window in windows:
        # A checked copy: the record keeps the rectangle that was measured,
        # zero-sized or not, because callers tell a collapsed window from a
        # failed measurement by it.
        geometry = coerce_geometry(window.get("geometry"))
        window["display"] = _showing(geometry, displays) if geometry else None


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
