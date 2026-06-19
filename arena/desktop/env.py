"""Desktop environment/tool detection."""
from __future__ import annotations

import os
import shutil


def _detect_desktop_env() -> dict:
    """Detect the desktop environment and available tools."""
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "")
    display = os.environ.get("DISPLAY", "")
    session_type = os.environ.get("XDG_SESSION_TYPE") or ("wayland" if wayland_display else ("x11" if display else "unknown"))
    desktop = os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION", "")
    return {
        "session_type": session_type,
        "desktop": desktop,
        "desktop_session": os.environ.get("DESKTOP_SESSION", ""),
        "wayland": bool(wayland_display),
        "x11": bool(display),
        "has_ydotool": shutil.which("ydotool") is not None,
        "has_xdotool": shutil.which("xdotool") is not None,
        "has_spectacle": shutil.which("spectacle") is not None,
        "has_grim": shutil.which("grim") is not None,
        "has_scrot": shutil.which("scrot") is not None,
        "has_wtype": shutil.which("wtype") is not None,
    }
