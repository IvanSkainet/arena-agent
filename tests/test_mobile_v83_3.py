"""Tests for v3.83.3 additions: sensors parser, scroll, key_combo,
letter/digit keys, and screenshot max_size (long-side downscale)."""
from __future__ import annotations

import io

from arena.mobile import adb as _adb  # noqa: F401
from arena.mobile import input as _input
from arena.mobile import screenshot as _screenshot
from arena.mobile import sensors as _sensors


# ---------------------------------------------------------------------------
# input.key — letters, digits, modifiers now accepted
# ---------------------------------------------------------------------------
def test_key_accepts_single_letters(monkeypatch):
    """Physical-keyboard forwarding needs A-Z. `_normalise_key` should
    accept them without polluting the allowlist error text."""
    from arena.mobile.input import _normalise_key
    for k in ("A", "Z", "m", "keycode_g"):
        upper, err = _normalise_key(k)
        assert err is None, f"{k!r} should be accepted"
        assert upper.isupper() and len(upper) == 1

    for k in ("0", "9", "3"):
        upper, err = _normalise_key(k)
        assert err is None, f"{k!r} should be accepted"
        assert upper.isdigit()


def test_key_still_rejects_dangerous_codes():
    from arena.mobile.input import _normalise_key
    for bad in ("POWER", "REBOOT", "CAMERA", "gibberish", "AA", "!"):
        _, err = _normalise_key(bad)
        assert err is not None, f"{bad!r} should be rejected"
        assert "allowlist" in err or "empty" in err or "string" in err


def test_key_accepts_new_named_codes():
    """v3.83.3 added PAGE_UP, F1-F12, COPY/PASTE/CUT etc."""
    from arena.mobile.input import _ALLOWED_KEYS
    for k in ("PAGE_UP", "PAGE_DOWN", "F1", "F12", "COPY", "PASTE",
              "SHIFT_LEFT", "CTRL_LEFT", "ALT_LEFT", "META_LEFT",
              "ZOOM_IN", "SEARCH", "NOTIFICATION"):
        assert k in _ALLOWED_KEYS, f"{k!r} missing from allowlist"


# ---------------------------------------------------------------------------
# input.key_combo — Ctrl+A style shortcuts
# ---------------------------------------------------------------------------
def test_key_combo_rejects_too_few_or_too_many():
    r = _input.key_combo("dummy", ["A"])
    assert r["ok"] is False and "2..4" in r["error"]
    r = _input.key_combo("dummy", ["A", "B", "C", "D", "E"])
    assert r["ok"] is False and "2..4" in r["error"]


def test_key_combo_rejects_disallowed_key():
    r = _input.key_combo("dummy", ["CTRL_LEFT", "POWER"])
    assert r["ok"] is False and "allowlist" in r["error"]


def test_key_combo_without_adb_returns_adb_hint():
    orig = _adb.find_adb
    _adb.find_adb = lambda: None
    _input.find_adb = lambda: None
    try:
        r = _input.key_combo("dummy", ["CTRL_LEFT", "A"])
    finally:
        _adb.find_adb = orig
        _input.find_adb = orig
    assert r["ok"] is False
    assert "adb not installed" in r["error"]


# ---------------------------------------------------------------------------
# input.scroll — mouse wheel emulation
# ---------------------------------------------------------------------------
def test_scroll_rejects_non_integer_coords():
    r = _input.scroll("dummy", 1.5, 200, vscroll=1)
    assert r["ok"] is False and "integer" in r["error"]


def test_scroll_requires_non_zero_axis():
    r = _input.scroll("dummy", 100, 200, vscroll=0, hscroll=0)
    assert r["ok"] is False and "non-zero" in r["error"]


def test_scroll_rejects_huge_delta():
    r = _input.scroll("dummy", 100, 200, vscroll=1000)
    assert r["ok"] is False and "out of range" in r["error"]


def test_scroll_without_adb_returns_hint():
    orig = _adb.find_adb
    _adb.find_adb = lambda: None
    _input.find_adb = lambda: None
    try:
        r = _input.scroll("dummy", 100, 200, vscroll=1)
    finally:
        _adb.find_adb = orig
        _input.find_adb = orig
    assert r["ok"] is False
    assert "adb not installed" in r["error"]


def test_scroll_falls_back_to_swipe_on_unknown_command(monkeypatch):
    """On Android versions that don't accept `input mouse scroll` we
    should transparently swipe instead so the user still sees motion."""
    class _R:
        returncode = 255
        stdout = ""
        stderr = "Error: Unknown command 'scroll'"
    monkeypatch.setattr(_input, "find_adb", lambda: "/usr/bin/adb")
    calls = []
    def _fake_run(args, serial=None, timeout=10):
        calls.append(args)
        if "scroll" in args:
            return _R()
        # Swipe fallback
        class _OK:
            returncode = 0
            stdout = ""
            stderr = ""
        return _OK()
    monkeypatch.setattr(_input, "run", _fake_run)
    r = _input.scroll("s", 500, 800, vscroll=1)
    assert r["ok"] is True
    assert r["action"] == "scroll"
    assert r["fallback"] == "swipe"
    # One scroll attempt, one swipe fallback.
    assert any("scroll" in a for a in calls)
    assert any("swipe" in a for a in calls)


# ---------------------------------------------------------------------------
# screenshot.capture — max_size vs max_width for landscape
# ---------------------------------------------------------------------------
def _synthetic_png(width: int, height: int) -> bytes:
    """Build a minimum-viable PNG with the given IHDR dims and a tiny
    IDAT so Pillow will actually decode it end-to-end."""
    try:
        from PIL import Image
    except Exception:
        return b""
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color=(50, 100, 150)).save(buf, format="PNG")
    return buf.getvalue()


def test_screenshot_max_size_downscales_by_long_side_in_landscape(monkeypatch):
    """max_size=720 on a 3200x1440 landscape screen must produce
    720x324 (long side capped). max_width=720 does the same in
    portrait but would collapse landscape to 720xTINY — that was the
    v3.83.2 complaint from the user."""
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        import pytest
        pytest.skip("Pillow not installed")

    png = _synthetic_png(3200, 1440)  # landscape POCO F7 Pro
    class _R:
        returncode = 0
        stdout = png
        stderr = b""

    monkeypatch.setattr(_screenshot, "find_adb", lambda: "/usr/bin/adb")
    monkeypatch.setattr(_screenshot, "run", lambda *a, **kw: _R())

    r = _screenshot.capture("dummy", max_size=720, format="webp", quality=80)
    assert r["ok"] is True
    assert r["source_width"] == 3200 and r["source_height"] == 1440
    # Long side 3200 → 720, short side scales to 720*(1440/3200) = 324
    assert r["width"] == 720
    assert r["height"] == 324
    assert r["downscaled"] is True


def test_screenshot_max_size_takes_priority_over_max_width(monkeypatch):
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        import pytest
        pytest.skip("Pillow not installed")
    png = _synthetic_png(1440, 3200)  # portrait
    class _R:
        returncode = 0
        stdout = png
        stderr = b""
    monkeypatch.setattr(_screenshot, "find_adb", lambda: "/usr/bin/adb")
    monkeypatch.setattr(_screenshot, "run", lambda *a, **kw: _R())
    # If max_size wins, long side (3200) caps to 720 → 324x720.
    r = _screenshot.capture("dummy", max_width=100, max_size=720,
                            format="webp", quality=80)
    assert r["height"] == 720
    assert r["width"] == 324


# ---------------------------------------------------------------------------
# sensors — parse list + recent events from real dumpsys snippets
# ---------------------------------------------------------------------------
_SENSOR_DUMP = """\
Sensor Device:
Total 3 h/w sensors, 3 running 0 disabled clients:

Sensor List:
0x0100000b) lsm6dsv Accelerometer Non-wakeup | STMicro         | ver: 18176 | type: android.sensor.accelerometer(1) | perm: n/a | flags: 0x00000980
\tcontinuous | minRate=1.00Hz | maxRate=479.85Hz | FIFO (max,reserved) = (10000, 3000) events
0x01000033) stk3bfx Ambient Light Sensor Non-wakeup | STMicro         | ver: 1 | type: android.sensor.light(5) | perm: n/a | flags: 0x00000102
\ton-change | minRate=5.00Hz | maxRate=50.00Hz | resolution=1.0
0x0100010f) proximity Non-wakeup | STMicro         | ver: 2 | type: android.sensor.proximity(8) | perm: n/a | flags: 0x00000103
\ton-change | minRate=5.00Hz | maxRate=5.00Hz

Recent Sensor events:
lsm6dsv Accelerometer Non-wakeup: last 3 events
\t 1 (ts=100.001, wall=19:44:27.248) 0.10, -9.80, 0.20, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 
\t 2 (ts=100.005, wall=19:44:27.249) 0.11, -9.79, 0.19, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 
\t 3 (ts=100.010, wall=19:44:27.250) 0.09, -9.81, 0.21, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 
stk3bfx Ambient Light Sensor Non-wakeup: last 1 events
\t 1 (ts=200.000, wall=19:44:28.100) 128.50, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 
proximity Non-wakeup: last 1 events
\t 1 (ts=300.000, wall=19:44:29.000) 5.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 0.00, 
"""


def test_sensors_parses_sensor_list_and_types():
    from arena.mobile.sensors import _parse_sensor_list
    got = _parse_sensor_list(_SENSOR_DUMP)
    assert len(got) == 3
    accel = got[0]
    assert accel["type_int"] == 1 and accel["type"] == "accelerometer"
    assert accel["vendor"] == "STMicro"
    assert accel["min_rate_hz"] == 1.0
    assert accel["max_rate_hz"] == 479.85
    assert accel["trigger_mode"] == "continuous"
    assert accel["fifo_max_events"] == 10000

    light = got[1]
    assert light["type_int"] == 5 and light["type"] == "light"
    assert light["trigger_mode"] == "on-change"
    assert light["resolution"] == 1.0

    prox = got[2]
    assert prox["type_int"] == 8 and prox["type"] == "proximity"


def test_sensors_parses_recent_events_with_channel_names():
    from arena.mobile.sensors import _parse_recent_events, _parse_sensor_list
    sensors = _parse_sensor_list(_SENSOR_DUMP)
    events = _parse_recent_events(_SENSOR_DUMP, sensors, limit=3)
    # Accelerometer: 3 events, values trimmed to non-zero tail
    accel_key = next(k for k in events if "Accelerometer" in k)
    accel = events[accel_key]
    assert accel["type"] == "accelerometer"
    assert accel["channels"] == ["x", "y", "z"]
    assert len(accel["events"]) == 3
    last = accel["events"][-1]
    assert last["values"] == [0.09, -9.81, 0.21]
    assert last["named"] == {"x": 0.09, "y": -9.81, "z": 0.21}
    assert last["ts"] == 100.010

    light_key = next(k for k in events if "Light" in k)
    light = events[light_key]
    assert light["type"] == "light"
    assert light["events"][-1]["named"] == {"lux": 128.5}

    prox_key = next(k for k in events if "proximity" in k.lower())
    prox = events[prox_key]
    assert prox["events"][-1]["named"] == {"cm": 5.0}


def test_sensors_list_without_adb_returns_hint():
    orig = _adb.find_adb
    _adb.find_adb = lambda: None
    _sensors.find_adb = lambda: None
    try:
        r = _sensors.list_sensors("dummy")
    finally:
        _adb.find_adb = orig
        _sensors.find_adb = orig
    assert r["ok"] is False
    assert "adb not installed" in r["error"]


def test_sensors_events_per_sensor_is_clamped_to_10():
    """Caller-supplied limit must never break the parser."""
    from arena.mobile.sensors import _parse_recent_events, _parse_sensor_list
    sensors = _parse_sensor_list(_SENSOR_DUMP)
    events = _parse_recent_events(_SENSOR_DUMP, sensors, limit=99)
    # Accelerometer had 3 events available, so 3 back (not 99).
    accel_key = next(k for k in events if "Accelerometer" in k)
    assert len(events[accel_key]["events"]) == 3


# ---------------------------------------------------------------------------
# handlers dataclass — v3.83.3 fields
# ---------------------------------------------------------------------------
def test_mobile_handlers_dataclass_has_v83_3_fields():
    """Baseline check that the v3.83.3 fields are still there. The
    exact field set (updated when we add new handlers) lives in
    test_mobile_v83_5.py so tests can grow without touching each
    other."""
    from arena.mobile.handlers import MobileHandlers
    v83_3_baseline = {"list_devices", "device_info", "screenshot", "tap", "swipe",
                      "type_text", "key_event", "shell", "packages", "gesture",
                      "ui_dump", "tap_by",
                      "helpers_status", "helpers_install",
                      "ime_status", "ime_set", "ime_reset", "paste",
                      "sensors", "scroll", "key_combo"}
    got = {f.name for f in MobileHandlers.__dataclass_fields__.values()}
    missing = v83_3_baseline - got
    assert not missing, f"v3.83.3 handlers missing: {missing}"


# ---------------------------------------------------------------------------
# v3.83.4 additions — raw screencap parser, FLAG_SECURE detector,
# probe_others catch-all, and the chain-based Live-view scheduler shape.
# ---------------------------------------------------------------------------
def test_screenshot_raw_header_parses_both_12_and_16_byte_variants():
    import struct
    from arena.mobile.screenshot import _parse_raw_header
    # 16-byte header (modern Android 10+): width, height, format,
    # colorspace. 3200x1440 landscape POCO frame + RGBA.
    header16 = struct.pack("<IIII", 3200, 1440, 1, 0) + b"\x00" * 32
    got = _parse_raw_header(header16)
    assert got == (3200, 1440, "RGBA", 4, 16)
    # 12-byte header (older Android): width, height, format. Pad the
    # 4-byte "colorspace" slot with an obviously-out-of-range value
    # (99) so the 16-byte parser rejects it and falls through to the
    # 12-byte path. This mirrors what a real legacy screencap emits —
    # the bytes after the 12-byte header are pixel data, not a
    # coincidentally-valid colorspace enum.
    header12 = struct.pack("<III", 1080, 2400, 1) + b"\x63\x00\x00\x00" + b"\x00" * 32
    got = _parse_raw_header(header12)
    assert got == (1080, 2400, "RGBA", 4, 12)
    # Garbage bytes — must return None so caller falls back to PNG.
    assert _parse_raw_header(b"") is None
    assert _parse_raw_header(b"\x00" * 30) is None


def test_screenshot_secure_frame_detector_flags_black_frame():
    try:
        from PIL import Image
    except Exception:
        import pytest
        pytest.skip("Pillow not installed")
    from arena.mobile.screenshot import _looks_secure_frame
    black = Image.new("RGB", (100, 200), color=(0, 0, 0))
    assert _looks_secure_frame(black) is True
    # A colourful gradient must NOT trip the detector (regression:
    # earlier iterations with a naive avg-brightness check flagged
    # real dark-mode UIs as secure).
    grad = Image.new("RGB", (100, 200))
    for x in range(100):
        for y in range(200):
            grad.putpixel((x, y), (x * 2, y % 256, (x + y) % 256))
    assert _looks_secure_frame(grad) is False


def test_screenshot_capture_returns_capture_and_encode_ms(monkeypatch):
    """The new latency-breakdown fields must always be present so the
    Dashboard can render its "cap X + enc Y + net Z" meta line without
    conditional guards."""
    try:
        from PIL import Image  # noqa: F401
    except Exception:
        import pytest
        pytest.skip("Pillow not installed")
    from arena.mobile import screenshot as _s
    import io as _io, struct as _st
    from PIL import Image as _PI
    # Build a synthetic PNG for the -p fallback path.
    buf = _io.BytesIO()
    _PI.new("RGB", (100, 200), color=(30, 60, 90)).save(buf, format="PNG")
    class _R:
        returncode = 0
        stdout = buf.getvalue()
        stderr = b""
    monkeypatch.setattr(_s, "find_adb", lambda: "/usr/bin/adb")
    monkeypatch.setattr(_s, "run", lambda *a, **kw: _R())
    r = _s.capture("dummy", max_size=50, format="webp", quality=80,
                   force_png_source=True)
    assert r["ok"] is True
    assert r["capture_mode"] == "png"
    assert "capture_ms" in r and isinstance(r["capture_ms"], int)
    assert "encode_ms" in r and isinstance(r["encode_ms"], int)


def test_probe_others_filters_pii(monkeypatch):
    """Bug regression: probe_others must NEVER emit ICCID/IMSI/MAC-shaped
    values. Feeds a getprop dump seeded with three PII-looking strings
    and asserts none of them appear in the output."""
    from arena.mobile import devices_probes as _p
    fake = (
        "[ro.miui.ui.version.name]: [V816]\n"
        "[ro.opengles.version]: [196610]\n"
        "[ro.hardware.gpu]: [adreno]\n"
        "[persist.sys.usb.config]: [mtp,adb]\n"
        "[ro.build.version.security_patch]: [2026-06-01]\n"
        "[ro.serialno]: [DEVICESERIAL123]\n"                    # must be excluded
        "[gsm.sim.iccid]: [8970199912345678901]\n"              # must be excluded
        "[wifi.interface.macaddr]: [aa:bb:cc:dd:ee:ff]\n"       # MAC — must be excluded
        "[ril.pending.count]: [1234567890]\n"                   # 10+ digit — excluded
    )
    def _fake_sh(serial, args, timeout=5):
        if args[:1] == ["getprop"]:
            return fake
        return ""
    monkeypatch.setattr(_p, "_sh", _fake_sh)
    r = _p.probe_others("dummy")
    o = r["others"]
    # Whitelisted keys must appear.
    assert "ro.miui.ui.version.name" in o
    assert "ro.opengles.version" in o
    assert "ro.hardware.gpu" in o
    assert "persist.sys.usb.config" in o
    assert "ro.build.version.security_patch" in o
    # Blacklisted must NOT appear anywhere in the output.
    dumped = str(r)
    assert "DEVICESERIAL123" not in dumped
    assert "8970199912345678901" not in dumped
    assert "aa:bb:cc:dd:ee:ff" not in dumped
    assert "1234567890" not in dumped


def test_probe_others_stable_key_ordering(monkeypatch):
    from arena.mobile import devices_probes as _p
    fake = (
        "[ro.miui.foo]: [1]\n"
        "[ro.opengles.version]: [2]\n"
        "[dalvik.vm.heapsize]: [512m]\n"
        "[persist.debug.a]: [b]\n"
    )
    monkeypatch.setattr(_p, "_sh",
        lambda serial, args, timeout=5: fake if args[:1] == ["getprop"] else "")
    keys = list(_p.probe_others("dummy")["others"].keys())
    assert keys == sorted(keys), "others keys must be sorted for stable UI"
