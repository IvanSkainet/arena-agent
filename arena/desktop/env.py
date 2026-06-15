"""Desktop environment/tool detection."""
from __future__ import annotations

import os
import shutil


def _detect_desktop_env() -> dict:
    """Detect the desktop environment and available tools."""
    session_type = os.environ.get("XDG_SESSION_TYPE", "unknown")
    wayland_display = os.environ.get("WAYLAND_DISPLAY", "")
    display = os.environ.get("DISPLAY", "")
    return {
        "session_type": session_type,
        "wayland": bool(wayland_display),
        "x11": bool(display),
        "has_ydotool": shutil.which("ydotool") is not None,
        "has_xdotool": shutil.which("xdotool") is not None,
        "has_spectacle": shutil.which("spectacle") is not None,
        "has_grim": shutil.which("grim") is not None,
        "has_scrot": shutil.which("scrot") is not None,
        "has_wtype": shutil.which("wtype") is not None,
    }
