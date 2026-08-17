"""Runtime-derived desktop capability fragments."""
from __future__ import annotations

from typing import Any


def windows_desktop_capability(env: dict[str, Any]) -> dict[str, Any]:
    """Describe native Win32 surfaces from the same flags handlers consume."""
    windows = bool(env.get("has_win32_windows"))
    screenshot = bool(env.get("has_win32_screenshot"))
    input_available = bool(env.get("has_win32_input"))

    def surface(available: bool, *, pending: str) -> dict[str, Any]:
        result: dict[str, Any] = {
            "available": available,
            "backend": "native-win32" if available else pending,
        }
        if not available:
            result["reason"] = "native Windows backend was not detected"
        return result

    return {
        "available": windows or screenshot or input_available,
        "windows": surface(windows, pending="pending-win32"),
        "active_window": surface(windows, pending="pending-win32"),
        "screenshot": surface(screenshot, pending="pending-win32"),
        "input": surface(input_available, pending="pending-win32"),
    }
