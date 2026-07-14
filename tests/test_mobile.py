"""Arena mobile domain regressions.

These tests never require ADB to be installed or a device to be connected.
They exercise contract shape, safety guards, and cross-platform paths
using mocks + real module surface.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from arena.mobile import adb as _adb
from arena.mobile import devices as _devices
from arena.mobile import input as _input
from arena.mobile import packages as _packages
from arena.mobile import screenshot as _screenshot
from arena.mobile import shell as _shell


# ---------------------------------------------------------------------------
# adb.py — cross-platform discovery
# ---------------------------------------------------------------------------
def test_adb_install_hint_is_platform_specific():
    hint = _adb.install_hint()
    lower = hint.lower()
    assert "adb" in lower or "platform-tools" in lower or "android" in lower
    # Every hint must contain at least one actionable install verb.
    assert any(v in lower for v in ("pacman", "apt", "brew", "winget", "scoop", "developer.android.com"))


def test_adb_candidates_dedup_and_executable():
    """Whatever _candidates returns, every entry must exist and be executable."""
    import os
    seen = set()
    for path in _adb._candidates():
        assert path not in seen, f"duplicate candidate {path}"
        seen.add(path)
        assert os.path.isfile(path)
        assert os.access(path, os.X_OK)


def test_subprocess_kwargs_hides_console_on_windows_only():
    """Same lesson as ZeroTier — creationflags on Windows only."""
    import platform as _p
    kw = _adb._SUBPROCESS_KWARGS
    if _p.system().lower() == "windows":
        assert "creationflags" in kw
        assert kw["creationflags"] & 0x08000000
    else:
        assert kw == {}


def test_adb_not_found_error_type():
    """AdbNotFoundError is a RuntimeError subclass so callers can except broadly."""
    assert issubclass(_adb.AdbNotFoundError, RuntimeError)


# ---------------------------------------------------------------------------
# devices.py — output parsing
# ---------------------------------------------------------------------------
def test_parse_devices_regular():
    sample = (
        "List of devices attached\n"
        "ABC123XYZ              device usb:1-2 product:poco model:POCO_F7_Pro device:volla transport_id:5\n"
    )
    devs = _devices._parse_devices(sample)
    assert len(devs) == 1
    d = devs[0]
    assert d["serial"] == "ABC123XYZ"
    assert d["state"] == "device"
    assert d["product"] == "poco"
    assert d["model"] == "POCO_F7_Pro"
    assert d["usb"] == "1-2"
    assert d["transport_id"] == "5"
    assert d["ip"] is None


def test_parse_devices_unauthorized():
    sample = (
        "List of devices attached\n"
        "ABC123XYZ              unauthorized usb:1-2 transport_id:3\n"
    )
    devs = _devices._parse_devices(sample)
    assert devs[0]["state"] == "unauthorized"


def test_parse_devices_network_extracts_ip():
    sample = (
        "List of devices attached\n"
        "192.168.1.5:5555       device product:poco model:POCO_F7_Pro device:volla transport_id:7\n"
    )
    devs = _devices._parse_devices(sample)
    assert devs[0]["ip"] == "192.168.1.5"


def test_parse_devices_skips_noise():
    sample = (
        "* daemon not running; starting now at tcp:5037 *\n"
        "* daemon started successfully *\n"
        "List of devices attached\n"
        "\n"
    )
    assert _devices._parse_devices(sample) == []


def test_list_devices_without_adb_returns_actionable_shape():
    """When adb isn't installed the caller still gets a stable structure."""
    # Force the "not installed" branch by monkey-patching find_adb.
    orig = _adb.find_adb
    _adb.find_adb = lambda: None
    _devices.find_adb = lambda: None
    try:
        result = _devices.list_devices()
    finally:
        _adb.find_adb = orig
        _devices.find_adb = orig
    assert result["ok"] is False
    assert result["adb_installed"] is False
    assert result["devices"] == []
    assert result["hint"]  # actionable install hint present


# ---------------------------------------------------------------------------
# input.py — safety
# ---------------------------------------------------------------------------
def test_tap_rejects_non_integer_coords():
    r = _input.tap("dummy", "10", 20)
    assert r["ok"] is False and "integer" in r["error"]


def test_tap_rejects_negative_coords():
    r = _input.tap("dummy", -1, 5)
    assert r["ok"] is False and "range" in r["error"]


def test_swipe_rejects_zero_duration():
    r = _input.swipe("dummy", 0, 0, 100, 100, duration_ms=0)
    assert r["ok"] is False and "duration_ms" in r["error"]


def test_swipe_rejects_huge_duration():
    r = _input.swipe("dummy", 0, 0, 100, 100, duration_ms=999_999)
    assert r["ok"] is False and "duration_ms" in r["error"]


def test_type_rejects_non_string():
    r = _input.type_text("dummy", 12345)
    assert r["ok"] is False and "string" in r["error"]


def test_type_rejects_oversized_text():
    r = _input.type_text("dummy", "x" * 10_000)
    assert r["ok"] is False and "too long" in r["error"]


def test_type_rejects_empty_text():
    """Empty string triggers a bare NPE in InputShellCommand on Android
    15/16 — we filter it up front so the user gets an actionable error.
    """
    r = _input.type_text("dummy", "")
    assert r["ok"] is False
    assert "empty" in r["error"].lower() or "whitespace" in r["error"].lower()
    assert r.get("hint")
    assert r.get("action") == "type"


def test_type_rejects_whitespace_only():
    r = _input.type_text("dummy", "   \t \n")
    assert r["ok"] is False
    assert "empty" in r["error"].lower() or "whitespace" in r["error"].lower()


def test_type_rejects_non_ascii_cyrillic():
    """LatinIME on Android 15/16 (POCO F7 Pro / HyperOS reference)
    crashes with NullPointerException on any non-ASCII byte. We must
    reject it before ever invoking adb."""
    r = _input.type_text("dummy", "привет")
    assert r["ok"] is False
    assert "non-ASCII" in r["error"] or "ASCII" in r["error"]
    assert r.get("hint")
    assert "U+" in r.get("offending_codepoints", "")


def test_type_rejects_non_ascii_emoji():
    r = _input.type_text("dummy", "hello 🌍")
    assert r["ok"] is False
    assert "non-ASCII" in r["error"] or "ASCII" in r["error"]


def test_type_ascii_passes_validation():
    """Pure-ASCII text with the adb guard tripped should reach the
    'adb not installed' branch (not the non-ASCII branch)."""
    orig = _adb.find_adb
    _adb.find_adb = lambda: None
    _input.find_adb = lambda: None
    try:
        r = _input.type_text("dummy", "hello world 123")
    finally:
        _adb.find_adb = orig
        _input.find_adb = orig
    assert r["ok"] is False
    assert "adb not installed" in r["error"]


def test_friendly_type_error_covers_npe():
    from arena.mobile.input import _friendly_type_error
    raw = (
        "Exception occurred while executing 'text':\n"
        "java.lang.NullPointerException: Attempt to get length of null array"
    )
    friendly = _friendly_type_error(raw)
    assert "NullPointerException" in friendly
    assert "focused" in friendly.lower() or "IME" in friendly
    assert raw in friendly  # never hides the raw stack


def test_key_rejects_disallowed_keys():
    for bad in ("POWER", "REBOOT", "CAMERA", "gibberish"):
        r = _input.key("dummy", bad)
        assert r["ok"] is False and "allowlist" in r["error"], f"key={bad!r} unexpectedly passed"


def test_key_accepts_allowlisted_keys_by_name_case_insensitive():
    """The guard alone should not reject known keys — actual send may fail
    because adb is missing, but format-wise these names must pass."""
    from arena.mobile.input import _ALLOWED_KEYS
    for good in _ALLOWED_KEYS:
        # We only check that the allowlist check itself accepts it — the
        # actual subprocess call is short-circuited by the missing-adb guard.
        orig = _adb.find_adb
        _adb.find_adb = lambda: None
        _input.find_adb = lambda: None
        try:
            r = _input.key("dummy", good)
        finally:
            _adb.find_adb = orig
            _input.find_adb = orig
        # find_adb returned None so we should see "adb not installed", NOT
        # "not on the allowlist".
        assert "allowlist" not in (r.get("error") or ""), f"allowlisted key {good!r} rejected as bad key"


# ---------------------------------------------------------------------------
# shell.py — allowlist + metachar bypass prevention
# ---------------------------------------------------------------------------
def test_shell_rejects_disallowed_head_command():
    r = _shell.restricted_shell("dummy", "rm -rf /sdcard")
    assert r["ok"] is False and "allowlist" in r["error"]


def test_shell_rejects_semicolon_chain():
    """Metacharacter blocklist must fire before shlex splits the command."""
    r = _shell.restricted_shell("dummy", "getprop; rm -rf /sdcard")
    assert r["ok"] is False
    assert "metacharacter" in r["error"]


def test_shell_rejects_pipe_chain():
    r = _shell.restricted_shell("dummy", "cat /proc/version | grep Linux")
    assert r["ok"] is False and "metacharacter" in r["error"]


def test_shell_rejects_backtick_subshell():
    r = _shell.restricted_shell("dummy", "getprop `whoami`")
    assert r["ok"] is False and "metacharacter" in r["error"]


def test_shell_rejects_redirect():
    r = _shell.restricted_shell("dummy", "getprop > /sdcard/leak.txt")
    assert r["ok"] is False and "metacharacter" in r["error"]


def test_shell_rejects_settings_put():
    r = _shell.restricted_shell("dummy", "settings put system screen_off_timeout 3600000")
    assert r["ok"] is False and "settings" in r["error"]


def test_shell_rejects_pm_uninstall():
    r = _shell.restricted_shell("dummy", "pm uninstall com.google.android.gm")
    assert r["ok"] is False and "pm" in r["error"]


def test_shell_rejects_empty_command():
    r = _shell.restricted_shell("dummy", "   ")
    assert r["ok"] is False


def test_shell_rejects_oversized_command():
    r = _shell.restricted_shell("dummy", "getprop " + "x" * 10_000)
    assert r["ok"] is False and "too long" in r["error"]


# ---------------------------------------------------------------------------
# packages.py — filter sanitisation
# ---------------------------------------------------------------------------
def test_packages_rejects_shell_metachars_in_filter():
    for bad in ("foo;bar", "foo|bar", "foo&bar", "foo`bar", "$RANDOM"):
        r = _packages.list_packages("dummy", filter_text=bad)
        assert r["ok"] is False, f"filter {bad!r} unexpectedly accepted"
        assert "disallowed" in r["error"] or "adb not installed" in r["error"]


# ---------------------------------------------------------------------------
# screenshot.py — PNG parsing
# ---------------------------------------------------------------------------
def test_png_dimensions_reads_ihdr():
    """Verify our lightweight PNG size parser handles a minimal valid header."""
    # PNG signature + IHDR chunk for a 320x480 image.
    import struct
    header = b"\x89PNG\r\n\x1a\n"
    ihdr_length = struct.pack(">I", 13)
    ihdr_type = b"IHDR"
    ihdr_data = struct.pack(">II", 320, 480) + b"\x08\x02\x00\x00\x00"
    png = header + ihdr_length + ihdr_type + ihdr_data
    w, h = _screenshot._png_dimensions(png)
    assert (w, h) == (320, 480)


def test_png_dimensions_rejects_non_png():
    assert _screenshot._png_dimensions(b"") == (0, 0)
    assert _screenshot._png_dimensions(b"not a png at all") == (0, 0)


def test_screenshot_without_adb_returns_error():
    orig = _adb.find_adb
    _adb.find_adb = lambda: None
    _screenshot.find_adb = lambda: None
    try:
        r = _screenshot.capture("dummy")
    finally:
        _adb.find_adb = orig
        _screenshot.find_adb = orig
    assert r["ok"] is False
    assert "adb" in r["error"].lower() or "install" in (r.get("hint", "") or "").lower()


# ---------------------------------------------------------------------------
# handlers.py — dataclass field surface
# ---------------------------------------------------------------------------
def test_mobile_handlers_dataclass_fields():
    from arena.mobile.handlers import MobileHandlers
    expected = {"list_devices", "device_info", "screenshot", "tap", "swipe",
                "type_text", "key_event", "shell", "packages"}
    got = {f.name for f in MobileHandlers.__dataclass_fields__.values()}
    assert expected == got, f"MobileHandlers fields drift: {got - expected} / {expected - got}"
