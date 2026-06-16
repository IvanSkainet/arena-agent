"""Desktop/session environment bootstrap helpers."""
from __future__ import annotations

import os


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
