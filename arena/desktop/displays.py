"""Desktop display/output discovery helpers."""
from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Mapping
from typing import Any, Protocol


class DesktopExec(Protocol):
    """Shape of :func:`arena.desktop.exec._desktop_exec`.

    Written as a Protocol rather than
    ``Callable[[str, float], Awaitable[...]]`` because that alias makes
    ``timeout`` a *positional* parameter with no default, while every one of
    the 35 call sites passes it as a keyword -- so each was reported twice
    (unexpected-keyword + bad-argument-count) against a function that is in
    fact called correctly. 28 findings from one wrong alias.
    """

    def __call__(self, cmd: str, timeout: float = ...) -> Awaitable[dict[str, Any]]: ...
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_XRANDR_RE = re.compile(r"^(\S+) connected(?: primary)? (\d+)x(\d+)\+(-?\d+)\+(-?\d+)")
_KSCREEN_HEAD_RE = re.compile(r"^Output:\s*(\d+)\s+(\S+)(?:\s+(\S+))?")
_KSCREEN_GEOM_RE = re.compile(r"Geometry:\s*(-?\d+),(-?\d+)\s+(\d+)x(\d+)")


def _strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", str(text or ""))



def parse_xrandr_outputs(stdout: str) -> list[dict[str, Any]]:
    outputs = []
    for line in _strip_ansi(stdout).splitlines():
        match = _XRANDR_RE.match(line.strip())
        if not match:
            continue
        name, width, height, x, y = match.groups()
        outputs.append(
            {
                "name": name,
                "id": name,
                "connected": True,
                "enabled": True,
                "primary": " primary " in f" {line} ",
                "geometry": {"x": int(x), "y": int(y), "width": int(width), "height": int(height)},
                "backend": "xrandr",
            }
        )
    return outputs



def parse_kscreen_doctor_outputs(stdout: str) -> list[dict[str, Any]]:
    outputs: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for raw_line in _strip_ansi(stdout).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        head = _KSCREEN_HEAD_RE.match(line)
        if head:
            idx, name, uuid = head.groups()
            current = {"index": int(idx), "name": name, "id": name, "uuid": uuid or "", "backend": "kscreen_doctor"}
            outputs.append(current)
            continue
        if current is None:
            continue
        if line == "enabled":
            current["enabled"] = True
        elif line == "disabled":
            current["enabled"] = False
        elif line == "connected":
            current["connected"] = True
        elif line == "disconnected":
            current["connected"] = False
        elif line.startswith("priority "):
            try:
                current["priority"] = int(line.split()[-1])
            except ValueError:
                pass
        elif line.startswith("Scale: "):
            try:
                current["scale"] = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
        elif line.startswith("Rotation: "):
            current["rotation"] = line.split(":", 1)[1].strip()
        else:
            geom = _KSCREEN_GEOM_RE.search(line)
            if geom:
                x, y, width, height = map(int, geom.groups())
                current["geometry"] = {"x": x, "y": y, "width": width, "height": height}
    return [item for item in outputs if item.get("geometry")]



def match_display(outputs: list[dict[str, Any]], display: str | None) -> dict[str, Any] | None:
    display = str(display or "").strip()
    if not display:
        return None
    target = display.casefold()
    for output in outputs:
        if target in {str(output.get("name", "")).casefold(), str(output.get("id", "")).casefold(), str(output.get("uuid", "")).casefold()}:
            return output
    return None


async def _win32_displays() -> dict[str, Any]:
    """Ask user32: Windows has neither kscreen-doctor nor xrandr (#514)."""
    from arena.desktop.backends import windows_displays

    attempt: dict[str, Any] = {"tool": "user32.EnumDisplayMonitors", "ok": True}
    try:
        outputs = await asyncio.get_running_loop().run_in_executor(None, windows_displays.list_displays)
    except OSError as exc:
        attempt.update(ok=False, error=str(exc))
        return {"ok": False, "error": str(exc), "backend": "win32", "active_output": None, "count": 0, "displays": [], "attempts": [attempt]}
    active_output = next((output["name"] for output in outputs if output["active"]), None)
    return {"ok": True, "backend": "win32", "active_output": active_output, "count": len(outputs), "displays": outputs, "attempts": [attempt]}


# What each Linux tool is asked, and what reads its answer.
_TOOLS = {
    "kscreen_doctor": ("kscreen-doctor -o 2>/dev/null", parse_kscreen_doctor_outputs),
    "xrandr": ("xrandr --query 2>/dev/null", parse_xrandr_outputs),
}
_ACTIVE_OUTPUT = "qdbus6 org.kde.KWin /KWin org.kde.KWin.activeOutputName 2>/dev/null || qdbus org.kde.KWin /KWin org.kde.KWin.activeOutputName 2>/dev/null"


async def _ask(desktop_exec: DesktopExec, tool: str, attempts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run one tool and parse what it printed; no output and a failure both give no displays."""
    command, parse = _TOOLS[tool]
    result = await desktop_exec(command, timeout=6)
    attempts.append({"tool": tool, "ok": result.get("ok")})
    return parse(result.get("stdout") or "") if result.get("ok") else []


def _mark_active(outputs: list[dict[str, Any]], active_output: str) -> None:
    for output in outputs:
        output["active"] = bool(active_output and output.get("name") == active_output)


async def _linux_displays(desktop_exec: DesktopExec) -> dict[str, Any]:
    attempts: list[dict[str, Any]] = []
    qdbus = await desktop_exec(_ACTIVE_OUTPUT, timeout=4)
    active_output = (qdbus.get("stdout") or "").strip() if qdbus.get("ok") else ""
    backend = "kscreen_doctor"
    outputs = await _ask(desktop_exec, backend, attempts)
    _mark_active(outputs, active_output)
    for output in outputs:
        # kscreen-doctor does not say which output is primary; KWin's active one stands in.
        if output["active"]:
            output["primary"] = True
    if not outputs:
        backend = "xrandr"
        outputs = await _ask(desktop_exec, backend, attempts)
        _mark_active(outputs, active_output)
    return {"ok": True, "backend": backend if outputs else "none", "active_output": active_output or None, "count": len(outputs), "displays": outputs, "attempts": attempts}


async def get_displays(*, desktop_exec: DesktopExec, env: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """List the displays: from user32 on Windows, from kscreen-doctor or xrandr elsewhere."""
    if env is not None and env.get("has_win32_windows"):
        return await _win32_displays()
    return await _linux_displays(desktop_exec)
