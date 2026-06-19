"""Desktop/session environment bootstrap helpers."""
from __future__ import annotations

import os
import shutil
import subprocess


def _kwin_session_available() -> bool:
    qdbus = shutil.which("qdbus6") or shutil.which("qdbus")
    if not qdbus:
        return False
    try:
        proc = subprocess.run(
            [qdbus, "org.kde.KWin", "/KWin", "org.kde.KWin.activeOutputName"],
            capture_output=True,
            text=True,
            timeout=2,
            encoding="utf-8",
            errors="replace",
        )
        return proc.returncode == 0 and bool(proc.stdout.strip())
    except Exception:
        return False


def ensure_session_env() -> None:
    """Ensure critical Linux desktop/session environment variables are present."""
    if os.name == "nt":
        return

    uid = os.getuid()
    if not os.environ.get("XDG_RUNTIME_DIR"):
        xdg = f"/run/user/{uid}"
        if os.path.isdir(xdg):
            os.environ["XDG_RUNTIME_DIR"] = xdg

    if not os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        dbus_path = f"/run/user/{uid}/bus"
        if os.path.exists(dbus_path):
            os.environ["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={dbus_path}"

    if not os.environ.get("DISPLAY") and os.path.exists("/tmp/.X11-unix"):
        try:
            for xfile in os.listdir("/tmp/.X11-unix"):
                if xfile.startswith("X"):
                    os.environ["DISPLAY"] = f":{xfile[1:]}"
                    break
        except Exception:
            pass

    if not os.environ.get("WAYLAND_DISPLAY") and os.environ.get("XDG_RUNTIME_DIR"):
        wayland_sock = os.path.join(os.environ["XDG_RUNTIME_DIR"], "wayland-0")
        if os.path.exists(wayland_sock):
            os.environ["WAYLAND_DISPLAY"] = "wayland-0"

    if not os.environ.get("XDG_SESSION_TYPE"):
        if os.environ.get("WAYLAND_DISPLAY"):
            os.environ["XDG_SESSION_TYPE"] = "wayland"
        elif os.environ.get("DISPLAY"):
            os.environ["XDG_SESSION_TYPE"] = "x11"

    if not os.environ.get("XDG_CURRENT_DESKTOP"):
        desktop = os.environ.get("DESKTOP_SESSION", "")
        if desktop:
            os.environ["XDG_CURRENT_DESKTOP"] = desktop
        elif _kwin_session_available():
            os.environ["XDG_CURRENT_DESKTOP"] = "KDE"

    if not os.environ.get("DESKTOP_SESSION") and os.environ.get("XDG_CURRENT_DESKTOP"):
        os.environ["DESKTOP_SESSION"] = os.environ["XDG_CURRENT_DESKTOP"]
