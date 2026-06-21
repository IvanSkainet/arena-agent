"""Desktop display/output discovery helpers."""
from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import Any

DesktopExec = Callable[[str, float], Awaitable[dict[str, Any]]]
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


async def get_displays(*, desktop_exec: DesktopExec) -> dict[str, Any]:
    attempts = []
    active_output = ""
    qdbus = await desktop_exec("qdbus6 org.kde.KWin /KWin org.kde.KWin.activeOutputName 2>/dev/null || qdbus org.kde.KWin /KWin org.kde.KWin.activeOutputName 2>/dev/null", timeout=4)
    if qdbus.get("ok"):
        active_output = (qdbus.get("stdout") or "").strip()
    result = await desktop_exec("kscreen-doctor -o 2>/dev/null", timeout=6)
    attempts.append({"tool": "kscreen_doctor", "ok": result.get("ok")})
    if result.get("ok") and (result.get("stdout") or "").strip():
        outputs = parse_kscreen_doctor_outputs(result.get("stdout", ""))
        if outputs:
            for output in outputs:
                output["active"] = bool(active_output and output.get("name") == active_output)
                if active_output and output.get("name") == active_output:
                    output["primary"] = True
            return {"ok": True, "backend": "kscreen_doctor", "active_output": active_output or None, "count": len(outputs), "displays": outputs, "attempts": attempts}
    result = await desktop_exec("xrandr --query 2>/dev/null", timeout=6)
    attempts.append({"tool": "xrandr", "ok": result.get("ok")})
    if result.get("ok") and (result.get("stdout") or "").strip():
        outputs = parse_xrandr_outputs(result.get("stdout", ""))
        if outputs:
            for output in outputs:
                output["active"] = bool(active_output and output.get("name") == active_output)
            return {"ok": True, "backend": "xrandr", "active_output": active_output or None, "count": len(outputs), "displays": outputs, "attempts": attempts}
    return {"ok": True, "backend": "none", "active_output": active_output or None, "count": 0, "displays": [], "attempts": attempts}


__all__ = ["get_displays", "match_display", "parse_kscreen_doctor_outputs", "parse_xrandr_outputs"]
