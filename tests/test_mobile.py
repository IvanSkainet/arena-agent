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


def test_type_non_ascii_without_adbkeyboard_returns_actionable_error(monkeypatch):
    """When ADBKeyboard is not active, non-ASCII must be rejected with a
    hint that points the caller at the helper install/activate flow."""
    from arena.mobile import helpers as _helpers
    monkeypatch.setattr(_helpers, "ime_status", lambda serial: {
        "ok": True,
        "adbkeyboard_installed": False,
        "adbkeyboard_active": False,
        "current": "com.google.android.inputmethod.latin/...",
    })
    r = _input.type_text("dummy", "привет")
    assert r["ok"] is False
    assert "non-ASCII" in r["error"] or "ASCII" in r["error"]
    assert r.get("hint")
    assert "ADBKeyboard" in r["hint"]
    assert "U+" in r.get("offending_codepoints", "")
    assert r.get("route") == "blocked"
    assert r.get("adbkeyboard_installed") is False


def test_type_non_ascii_routes_through_adbkeyboard_when_active(monkeypatch):
    """When ADBKeyboard IS the active IME, non-ASCII must be sent via
    the ADB_INPUT_B64 broadcast instead of `input text`."""
    from arena.mobile import helpers as _helpers
    monkeypatch.setattr(_helpers, "ime_status", lambda serial: {
        "ok": True,
        "adbkeyboard_installed": True,
        "adbkeyboard_active": True,
        "current": _helpers.ADBKEYBOARD_SERVICE,
    })
    captured: dict[str, object] = {}
    def _fake_paste(serial, text):
        captured["serial"] = serial
        captured["text"] = text
        return {"ok": True, "action": "paste", "chars": len(text),
                "stdout": "Broadcast completed: result=0",
                "stderr": "", "exit_code": 0}
    monkeypatch.setattr(_helpers, "paste_text", _fake_paste)
    r = _input.type_text("dummy", "привет 🌍")
    assert r["ok"] is True
    assert captured["text"] == "привет 🌍"
    assert r.get("route") == "adbkeyboard"
    assert r.get("action") == "type"
    assert r.get("chars") == 8


def test_type_non_ascii_emoji_blocked_without_helper(monkeypatch):
    """Emoji-only payload still hits the block path when ADBKeyboard is
    not the active IME."""
    from arena.mobile import helpers as _helpers
    monkeypatch.setattr(_helpers, "ime_status", lambda serial: {
        "ok": False, "error": "adb not installed",
    })
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
def test_mobile_handlers_dataclass_has_expected_baseline():
    """Basic sanity — the exact field surface is asserted in
    tests/test_mobile_v83_3.py so it lives next to the newest additions.
    This test just guards the pre-v3.83 minimum so a plain rename here
    still trips CI."""
    from arena.mobile.handlers import MobileHandlers
    baseline = {"list_devices", "device_info", "screenshot", "tap", "swipe",
                "type_text", "key_event", "shell", "packages"}
    got = {f.name for f in MobileHandlers.__dataclass_fields__.values()}
    assert baseline.issubset(got), f"baseline handlers missing: {baseline - got}"


# ---------------------------------------------------------------------------
# ui.py — bounds parsing, matcher, no-adb guards, and tap_by validation
# ---------------------------------------------------------------------------
def test_ui_dump_without_adb_returns_error():
    from arena.mobile import ui as _ui
    orig = _adb.find_adb
    _adb.find_adb = lambda: None
    _ui.find_adb = lambda: None
    try:
        r = _ui.dump_ui("dummy")
    finally:
        _adb.find_adb = orig
        _ui.find_adb = orig
    assert r["ok"] is False
    assert "adb not installed" in r["error"]


def test_ui_dump_requires_serial():
    from arena.mobile import ui as _ui
    r = _ui.dump_ui("")
    assert r["ok"] is False
    assert "serial" in r["error"]


def test_ui_bounds_parser_reads_uiautomator_format():
    from arena.mobile.ui import _parse_bounds
    assert _parse_bounds("[0,0][1440,3200]") == (0, 0, 1440, 3200)
    assert _parse_bounds("[10,20][30,40]") == (10, 20, 30, 40)
    assert _parse_bounds("") is None
    assert _parse_bounds("garbage") is None
    # Negative coords do occur on floating windows in gesture nav.
    assert _parse_bounds("[-5,10][100,200]") == (-5, 10, 100, 200)


def test_ui_matcher_modes():
    from arena.mobile.ui import _make_matcher
    exact = _make_matcher("exact")
    contains = _make_matcher("contains")
    rx = _make_matcher("regex")
    assert exact("hello", "hello") is True
    assert exact("hello world", "hello") is False
    assert contains("hello world", "world") is True
    assert contains("abc", "xyz") is False
    assert rx("com.android.settings:id/search_btn", r"search_\w+") is True
    assert rx("nope", r"^wrong$") is False
    # Broken regex fails soft (no exception, just no match).
    assert rx("anything", r"[") is False


def test_tap_by_requires_at_least_one_selector():
    from arena.mobile import ui as _ui
    r = _ui.tap_by("dummy")
    assert r["ok"] is False
    assert "id, text, desc" in r["error"]


def test_tap_by_rejects_invalid_match_mode():
    from arena.mobile import ui as _ui
    r = _ui.tap_by("dummy", id="anything", match="fuzzy")
    assert r["ok"] is False
    assert "match mode" in r["error"]


def test_tap_by_without_adb_returns_error():
    """tap_by delegates to dump_ui which triggers the adb guard."""
    from arena.mobile import ui as _ui
    orig = _adb.find_adb
    _adb.find_adb = lambda: None
    _ui.find_adb = lambda: None
    try:
        r = _ui.tap_by("dummy", id="com.example:id/btn")
    finally:
        _adb.find_adb = orig
        _ui.find_adb = orig
    assert r["ok"] is False
    assert "adb not installed" in r["error"]


def test_ui_interactive_predicate():
    """The interactive filter should catch clickable/scrollable AND
    label-only nodes that carry text or content-desc."""
    import xml.etree.ElementTree as ET
    from arena.mobile.ui import _is_interactive

    def _node(**attrs):
        e = ET.Element("node")
        for k, v in attrs.items():
            e.set(k, v)
        return e

    assert _is_interactive(_node(clickable="true"))
    assert _is_interactive(_node(scrollable="true"))
    assert _is_interactive(_node(text="Settings", clickable="false"))
    assert _is_interactive(_node(**{"content-desc": "Home button", "clickable": "false"}))
    # Nothing interactive → should be filtered out.
    assert not _is_interactive(_node(text="", clickable="false", scrollable="false"))


def test_dump_ui_parses_synthetic_xml(monkeypatch):
    """Feed a minimal known-good XML through dump_ui and assert on the
    parsed shape without an actual device."""
    from arena.mobile import ui as _ui
    from arena.mobile import adb as _adb2

    class _Result:
        def __init__(self):
            self.returncode = 0
            self.stdout = (
                b"<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>"
                b"<hierarchy rotation=\"0\">"
                b"<node index=\"0\" package=\"com.example\" class=\"android.widget.FrameLayout\" "
                b"clickable=\"false\" bounds=\"[0,0][1080,2400]\">"
                b"<node index=\"0\" text=\"Login\" resource-id=\"com.example:id/btn_login\" "
                b"class=\"android.widget.Button\" package=\"com.example\" "
                b"clickable=\"true\" bounds=\"[100,200][980,320]\" content-desc=\"\"/>"
                b"</node>"
                b"</hierarchy>"
            )
            self.stderr = b""

    monkeypatch.setattr(_ui, "find_adb", lambda: "/usr/bin/adb")
    monkeypatch.setattr(_ui, "run", lambda *a, **kw: _Result())
    r = _ui.dump_ui("dummy")
    assert r["ok"] is True
    assert r["root_package"] == "com.example"
    assert r["screen_bounds"] == [1080, 2400]
    assert r["rotation"] == 0
    # 2 total nodes, 1 interactive (the Button).
    assert r["node_count_total"] == 2
    assert len(r["nodes"]) == 1
    btn = r["nodes"][0]
    assert btn["text"] == "Login"
    assert btn["resource-id"] == "com.example:id/btn_login"
    assert btn["bounds_rect"] == [100, 200, 980, 320]
    assert btn["center"] == [540, 260]
    assert btn["width"] == 880 and btn["height"] == 120


# ---------------------------------------------------------------------------
# devices_probes.py — parsing helpers work on real-world snippets
# ---------------------------------------------------------------------------
def test_probe_display_modes_parses_pocopf7_dumpsys(monkeypatch):
    from arena.mobile import devices_probes as _p
    snippet = (
        "  DisplayDeviceInfo{... 1440 x 3200, modeId 1, renderFrameRate 120.00001, "
        "supportedRefreshRates [120.00001, 90.0, 60.000004], defaultModeId 1, "
        "mSupportedHdrTypes=[1, 2, 3, 4], "
        "RoundedCorner{position=TopLeft, radius=120, center=Point(120, 120)}"
    )
    monkeypatch.setattr(_p, "_sh", lambda serial, args, timeout=5: snippet)
    r = _p.probe_display_modes("dummy")
    d = r["display"]
    assert d["active_refresh_rate"] == 120.0
    assert d["supported_refresh_rates"] == [120.0, 90.0, 60.0]
    assert d["hdr_types"] == [1, 2, 3, 4]
    assert d["rounded_corner_radius_px"] == 120


def test_probe_network_masks_iccid_and_imsi(monkeypatch):
    """Regression: probe_network must ONLY extract non-PII operator info."""
    from arena.mobile import devices_probes as _p
    fake_getprop = (
        "[gsm.operator.alpha]: [beeline,]\n"
        "[gsm.operator.iso-country]: [ru,]\n"
        "[gsm.network.type]: [IWLAN,Unknown]\n"
        "[gsm.sim.state]: [LOADED,ABSENT]\n"
        "[gsm.operator.isroaming]: [false,false]\n"
        # These must be ignored — they contain PII.
        "[gsm.sim.imsi]: [250991234567890]\n"
        "[gsm.sim.iccid]: [8970199912345678901]\n"
    )
    # First call is `getprop`, second `settings get global mobile_data`.
    call = {"n": 0}
    def _fake_sh(serial, args, timeout=5):
        call["n"] += 1
        if args[:1] == ["getprop"]:
            return fake_getprop
        if args[:1] == ["settings"]:
            return "1"
        return ""
    monkeypatch.setattr(_p, "_sh", _fake_sh)
    r = _p.probe_network("dummy")
    n = r["network"]
    assert n["operator_alpha"] == "beeline"
    assert n["operator_iso"] == "ru"
    assert n["mobile_type"] == "IWLAN"
    assert n["sim_state"] == "LOADED"
    assert n["roaming"] is False
    assert n["data_enabled"] is True
    # Explicit privacy assertions.
    dumped = str(r)
    assert "imsi" not in dumped.lower()
    assert "iccid" not in dumped.lower()
    assert "250991234567890" not in dumped
    assert "8970199912345678901" not in dumped


def test_probe_ui_mode_parses_settings(monkeypatch):
    from arena.mobile import devices_probes as _p
    def _fake_sh(serial, args, timeout=5):
        # settings get global airplane_mode_on
        if args[:3] == ["settings", "get", "global"] and args[3] == "airplane_mode_on":
            return "0"
        if args[:3] == ["settings", "get", "secure"] and args[3] == "ui_night_mode":
            return "2"
        if args[:2] == ["dumpsys", "audio"]:
            return "  - ringer mode(internal) = 2\n"
        if args[:3] == ["settings", "get", "system"] and args[3] == "screen_off_timeout":
            return "30000"
        if args[:3] == ["settings", "get", "system"] and args[3] == "screen_brightness":
            return "128"
        if args[:3] == ["settings", "get", "system"] and args[3] == "accelerometer_rotation":
            return "1"
        return ""
    monkeypatch.setattr(_p, "_sh", _fake_sh)
    r = _p.probe_ui_mode("dummy")
    u = r["ui_mode"]
    assert u["airplane_mode"] is False
    assert u["night_mode"] == "dark"
    assert u["ringer_mode"] == "normal"
    assert u["screen_off_timeout_sec"] == 30
    assert u["screen_brightness_raw"] == 128
    assert u["auto_rotate"] is True


# ---------------------------------------------------------------------------
# gestures.py — allowlist + coordinate math (no adb needed)
# ---------------------------------------------------------------------------
def test_gestures_allowlist_is_stable():
    """Guard against silent additions/removals of gesture names — the UI
    depends on this being a closed set."""
    from arena.mobile.gestures import allowed_gestures
    got = set(allowed_gestures())
    expected = {
        "notifications", "quick_settings", "close_shade",
        "scroll_up", "scroll_down", "scroll_left", "scroll_right",
        "back_edge_left", "back_edge_right",
        "home_gesture", "recents_gesture",
    }
    assert got == expected, f"gesture allowlist drift: {got ^ expected}"


def test_gesture_rejects_unknown():
    from arena.mobile import gestures
    r = gestures.perform("dummy", "definitely_not_a_gesture")
    assert r["ok"] is False
    assert "allowlist" in r["error"]
    assert r.get("hint")


def test_gesture_rejects_non_string():
    from arena.mobile import gestures
    r = gestures.perform("dummy", None)  # type: ignore[arg-type]
    assert r["ok"] is False
    assert "string" in r["error"]


def test_gesture_without_adb_returns_adb_hint():
    """The gesture must go through the same adb-not-installed guard as swipe."""
    from arena.mobile import gestures
    orig = _adb.find_adb
    _adb.find_adb = lambda: None
    gestures.find_adb = lambda: None  # type: ignore[attr-defined]
    try:
        r = gestures.perform("dummy", "notifications")
    finally:
        _adb.find_adb = orig
        gestures.find_adb = orig  # type: ignore[attr-defined]
    assert r["ok"] is False
    assert "adb not installed" in r["error"]


# ---------------------------------------------------------------------------
# screenshot.py — format branches (no adb, small PIL-only checks)
# ---------------------------------------------------------------------------
def test_screenshot_capture_without_adb_returns_error():
    """Regression: screenshot pre-flight check runs before subprocess."""
    from arena.mobile import screenshot as _s
    orig = _adb.find_adb
    _adb.find_adb = lambda: None
    _s.find_adb = lambda: None
    try:
        r = _s.capture("dummy", max_width=360, quality=70, format="webp")
    finally:
        _adb.find_adb = orig
        _s.find_adb = orig
    assert r["ok"] is False
    assert "adb not installed" in r["error"]


def test_screenshot_encode_webp_and_jpeg_produce_bytes():
    """Direct check on `_encode`: given a Pillow image, webp/jpeg must
    return valid magic bytes."""
    try:
        from PIL import Image
    except Exception:
        import pytest
        pytest.skip("Pillow not installed on this host")
    from arena.mobile.screenshot import _encode
    import io as _io
    img = Image.new("RGB", (32, 32), color=(200, 30, 30))
    jpg_buf = _io.BytesIO()
    _encode(img, jpg_buf, fmt="jpeg", quality=80)
    assert jpg_buf.getvalue()[:3] == b"\xff\xd8\xff", "not JPEG"
    webp_buf = _io.BytesIO()
    _encode(img, webp_buf, fmt="webp", quality=80)
    v = webp_buf.getvalue()
    assert v[:4] == b"RIFF" and v[8:12] == b"WEBP", "not WebP"
