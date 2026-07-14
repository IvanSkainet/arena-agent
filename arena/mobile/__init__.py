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
from arena.mobile.helpers import (
    ADBKEYBOARD_PACKAGE,
    ADBKEYBOARD_SERVICE,
    ADBKEYBOARD_SHA256,
    ADBKEYBOARD_VERSION,
    bundled_apk_path,
    bundled_apk_status,
    ime_reset,
    ime_set_adbkeyboard,
    ime_status,
    install_adbkeyboard,
    paste_text,
)
from arena.mobile.input import key, swipe, tap, type_text
from arena.mobile.packages import list_packages
from arena.mobile.screenshot import capture as capture_screenshot
from arena.mobile.sensors import list_sensors
from arena.mobile.shell import restricted_shell
from arena.mobile.ui import dump_ui, tap_by
# Re-export the new scroll + key_combo primitives added in v3.83.3.
from arena.mobile.input import key_combo, scroll

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
    "dump_ui",
    "tap_by",
    "list_sensors",
    "scroll",
    "key_combo",
    "ADBKEYBOARD_PACKAGE",
    "ADBKEYBOARD_SERVICE",
    "ADBKEYBOARD_SHA256",
    "ADBKEYBOARD_VERSION",
    "bundled_apk_path",
    "bundled_apk_status",
    "install_adbkeyboard",
    "ime_status",
    "ime_set_adbkeyboard",
    "ime_reset",
    "paste_text",
    "MobileHandlers",
    "make_mobile_handlers",
]
