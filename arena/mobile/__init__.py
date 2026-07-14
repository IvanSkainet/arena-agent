"""Arena mobile domain — Phase 1 (Android via ADB).

See docs/MOBILE_SUPPORT_ROADMAP.md for the design rationale.
"""
from arena.mobile.adb import (
    AdbNotFoundError,
    adb_version,
    find_adb,
    install_hint,
    run,
)
from arena.mobile.devices import device_info, list_devices
from arena.mobile.gestures import allowed_gestures, perform as perform_gesture
from arena.mobile.handlers import MobileHandlers, make_mobile_handlers
from arena.mobile.input import key, swipe, tap, type_text
from arena.mobile.packages import list_packages
from arena.mobile.screenshot import capture as capture_screenshot
from arena.mobile.shell import restricted_shell

__all__ = [
    "AdbNotFoundError",
    "adb_version",
    "find_adb",
    "install_hint",
    "run",
    "list_devices",
    "device_info",
    "capture_screenshot",
    "tap",
    "swipe",
    "type_text",
    "key",
    "restricted_shell",
    "list_packages",
    "allowed_gestures",
    "perform_gesture",
    "MobileHandlers",
    "make_mobile_handlers",
]
