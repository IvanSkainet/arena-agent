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
# v3.84.0: batch executor.
from arena.mobile.batch import ALLOWED_TYPES as BATCH_STEP_TYPES, run_batch
# v3.84.1: camera automation.
from arena.mobile.camera import (
    capture_and_pull as camera_capture_and_pull,
    launch as camera_launch,
    latest_photo as camera_latest_photo,
    list_photos as camera_list_photos,
    pull_photo as camera_pull_photo,
    shutter as camera_shutter,
)
# Re-export the new scroll + key_combo primitives added in v3.83.3.
from arena.mobile.input import key_combo, scroll

# v3.83.5: wireless ADB + generic APK install.
from arena.mobile.wireless import (
    connect as wireless_connect,
    disconnect as wireless_disconnect,
    pair as wireless_pair,
)
from arena.mobile.apk_install import (
    STAGING_ROOT as APK_STAGING_ROOT,
    install as install_apk,
    prepare as prepare_apk,
    save_upload,
)
# v3.84.2: screen recording.
from arena.mobile.recording import (
    list_recordings,
    pull_recording,
    purge_recordings,
    record_sync,
    start_async as start_async_recording,
    stop_async as stop_async_recording,
)
# v3.84.3: live H.264 mirroring
from arena.mobile.mirror import (
    get_or_start as mirror_get_or_start,
    stats as mirror_stats,
    stop_all as mirror_stop_all,
)

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
    # v3.83.5
    "wireless_pair",
    "wireless_connect",
    "wireless_disconnect",
    "APK_STAGING_ROOT",
    "prepare_apk",
    "install_apk",
    # v3.84.0
    "BATCH_STEP_TYPES",
    "run_batch",
    # v3.84.1
    "camera_capture_and_pull",
    "camera_launch",
    "camera_latest_photo",
    "camera_list_photos",
    "camera_pull_photo",
    "camera_shutter",
    # v3.84.2
    "list_recordings",
    "pull_recording",
    "purge_recordings",
    "record_sync",
    "save_upload",
    "start_async_recording",
    "stop_async_recording",
    # v3.84.3
    "mirror_get_or_start",
    "mirror_stats",
    "mirror_stop_all",
    "MobileHandlers",
    "make_mobile_handlers",
]
