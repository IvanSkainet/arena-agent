"""Tests for v3.84.1: camera module + gesture statusbar-cmd fast path.

These are traditional unit tests (mocked adb). The live smoke script
sits at `scripts/smoke_mobile.py` — see docs/MOBILE.md."""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# camera.launch — intent validation + adb guard
# ---------------------------------------------------------------------------
def test_camera_launch_rejects_unknown_intent():
    from arena.mobile import camera as _c
    r = _c.launch("dummy", intent="disko")
    assert r["ok"] is False
    assert "unknown intent" in r["error"]


def test_camera_launch_needs_adb(monkeypatch):
    from arena.mobile import camera as _c
    monkeypatch.setattr(_c, "find_adb", lambda: None)
    r = _c.launch("dummy")
    assert r["ok"] is False
    assert "adb not installed" in r["error"]


def test_camera_launch_success_shape(monkeypatch):
    from arena.mobile import camera as _c
    monkeypatch.setattr(_c, "find_adb", lambda: "/usr/bin/adb")

    class _R:
        returncode = 0
        stdout = "Starting: Intent { act=android.media.action.STILL_IMAGE_CAMERA }\n"
        stderr = ""
    captured: list = []
    def _fake_run(args, serial=None, timeout=10):
        captured.append(args)
        return _R()
    monkeypatch.setattr(_c, "run", _fake_run)
    r = _c.launch("dummy", intent="still", package="com.google.android.GoogleCamera")
    assert r["ok"] is True
    assert r["intent"] == "android.media.action.STILL_IMAGE_CAMERA"
    assert r["package"] == "com.google.android.GoogleCamera"
    # Verify adb args include the -p flag.
    assert "-p" in captured[0]
    assert "com.google.android.GoogleCamera" in captured[0]


# ---------------------------------------------------------------------------
# camera.list_photos — parses `ls -lt` output
# ---------------------------------------------------------------------------
def test_camera_list_photos_parses_typical_ls(monkeypatch):
    from arena.mobile import camera as _c
    monkeypatch.setattr(_c, "find_adb", lambda: "/usr/bin/adb")
    fake_ls = (
        "total 721483\n"
        "-rwxrwx--- 1 u0_a284 media_rw   1446772 2026-07-10 14:27 AGC_20260710_142758063.jpg\n"
        "-rwxrwx--- 2 u0_a284 media_rw 205621543 2026-07-07 15:48 VID_20260707_154752.mp4\n"
        "-rwxrwx--- 2 u0_a284 media_rw 353871921 2026-07-07 15:46 VID_20260707_154544.mp4\n"
    )
    def _fake_sh(serial, args, timeout=10):
        if args[:2] == ["ls", "-lt"]:
            return (0, fake_ls, "")
        return (0, "", "")
    monkeypatch.setattr(_c, "_sh", _fake_sh)
    r = _c.list_photos("dummy", limit=5)
    assert r["ok"] is True
    assert r["count"] == 3
    names = [p["name"] for p in r["photos"]]
    assert "AGC_20260710_142758063.jpg" in names
    # First entry must be the newest by mtime (as `ls -lt` orders).
    assert r["photos"][0]["name"] == "AGC_20260710_142758063.jpg"
    assert r["photos"][0]["size_bytes"] == 1446772
    assert r["photos"][0]["path"].endswith("Camera/AGC_20260710_142758063.jpg")


# ---------------------------------------------------------------------------
# camera.pull_photo — path validation + downscale
# ---------------------------------------------------------------------------
def test_camera_pull_rejects_relative_path(monkeypatch):
    from arena.mobile import camera as _c
    monkeypatch.setattr(_c, "find_adb", lambda: "/usr/bin/adb")
    r = _c.pull_photo("dummy", "relative/path.jpg")
    assert r["ok"] is False
    assert "absolute" in r["error"]


def test_camera_pull_downscales_and_encodes(monkeypatch):
    """Feed a synthetic JPEG through pull_photo(max_size=…) and assert
    the returned blob is a decodable image of the requested dimension."""
    try:
        from PIL import Image
    except Exception:
        pytest.skip("Pillow not installed")
    from arena.mobile import camera as _c
    import base64
    import io as _io
    monkeypatch.setattr(_c, "find_adb", lambda: "/usr/bin/adb")
    src = Image.new("RGB", (2000, 3000), color=(50, 100, 150))
    buf = _io.BytesIO()
    src.save(buf, format="JPEG", quality=85)
    src_bytes = buf.getvalue()

    class _R:
        returncode = 0
        stdout = src_bytes
        stderr = b""
    monkeypatch.setattr(_c, "run", lambda *a, **kw: _R())
    r = _c.pull_photo("dummy", "/sdcard/DCIM/x.jpg",
                      max_size=512, format="webp", quality=80)
    assert r["ok"] is True
    assert r["mime"] == "image/webp"
    # Long side must be 512 after downscale (aspect preserved).
    assert max(r["width"], r["height"]) == 512
    # Bytes are base64-decodable.
    raw = base64.b64decode(r["bytes_b64"])
    Image.open(_io.BytesIO(raw)).verify()


# ---------------------------------------------------------------------------
# camera.shutter — falls back to auto-detect when no coords supplied
# ---------------------------------------------------------------------------
def test_camera_shutter_uses_auto_detect_when_no_coords(monkeypatch):
    from arena.mobile import camera as _c
    monkeypatch.setattr(_c, "find_adb", lambda: "/usr/bin/adb")

    def _fake_find_shutter(serial):
        return {"ok": True, "x": 720, "y": 2477,
                "resource_id": "com.android.camera:id/shutter_button",
                "source": "resource-id contains 'shutter'"}
    monkeypatch.setattr(_c, "find_shutter", _fake_find_shutter)
    tap_calls = []
    def _fake_tap(serial, x, y):
        tap_calls.append((x, y))
        return {"ok": True, "action": "tap", "x": x, "y": y}
    monkeypatch.setattr(_c, "_tap", _fake_tap)
    r = _c.shutter("dummy")
    assert r["ok"] is True
    assert r["shutter_x"] == 720
    assert r["shutter_y"] == 2477
    assert "resource-id" in r["detected_via"]
    assert tap_calls == [(720, 2477)]


def test_camera_shutter_uses_explicit_coords_when_given(monkeypatch):
    from arena.mobile import camera as _c
    monkeypatch.setattr(_c, "find_adb", lambda: "/usr/bin/adb")
    # Auto-detect would fail, but we're passing coords — should never
    # be called.
    monkeypatch.setattr(_c, "find_shutter",
        lambda s: {"ok": False, "error": "should not be called"})
    tap_calls = []
    monkeypatch.setattr(_c, "_tap",
        lambda s, x, y: (tap_calls.append((x, y)),
                         {"ok": True, "action": "tap", "x": x, "y": y})[1])
    r = _c.shutter("dummy", shutter_x=500, shutter_y=1800)
    assert r["ok"] is True
    assert r["shutter_x"] == 500 and r["shutter_y"] == 1800
    assert "caller-supplied" in r["detected_via"]


# ---------------------------------------------------------------------------
# gestures — shade actions now try `cmd statusbar` first
# ---------------------------------------------------------------------------
def test_gesture_shade_uses_statusbar_cmd(monkeypatch):
    """v3.84.1: the perform() fast path for shade gestures should
    hit `cmd statusbar` and NOT the swipe recipe when the phone
    accepts the command."""
    from arena.mobile import gestures as _g
    monkeypatch.setattr(_g, "find_adb", lambda: "/usr/bin/adb")

    calls = []
    class _OK:
        returncode = 0
        stdout = ""
        stderr = ""
    def _fake_run(args, serial=None, timeout=10):
        calls.append(list(args))
        return _OK()
    monkeypatch.setattr(_g, "run", _fake_run)
    r = _g.perform("dummy", "notifications")
    assert r["ok"] is True
    assert r["backend"] == "statusbar_cmd"
    assert r["cmd"] == "cmd statusbar expand-notifications"
    # No swipe call happened.
    assert not any("swipe" in str(a) for a in calls)


def test_gesture_shade_swipe_fallback_when_statusbar_refuses(monkeypatch):
    """If the SystemUI service rejects `cmd statusbar`, perform() must
    still deliver the gesture via the swipe recipe path (v3.83.4 behaviour)."""
    from arena.mobile import gestures as _g
    from arena.mobile import input as _input
    monkeypatch.setattr(_g, "find_adb", lambda: "/usr/bin/adb")

    class _FAIL:
        returncode = 1
        stdout = ""
        stderr = "not allowed"
    class _OK:
        returncode = 0
        stdout = ""
        stderr = ""
    def _fake_g_run(args, serial=None, timeout=10):
        return _FAIL()  # first call is `cmd statusbar …`
    monkeypatch.setattr(_g, "run", _fake_g_run)
    # `_screen_size` uses `_g.run` too; force a known size.
    monkeypatch.setattr(_g, "_screen_size", lambda s: (1440, 3200))
    # The subsequent swipe goes through input.swipe.
    swipe_calls = []
    def _fake_swipe(serial, x1, y1, x2, y2, duration_ms=300):
        swipe_calls.append((x1, y1, x2, y2, duration_ms))
        return {"ok": True, "action": "swipe"}
    monkeypatch.setattr(_g, "_low_swipe", _fake_swipe)
    r = _g.perform("dummy", "notifications")
    assert r["ok"] is True
    assert r["backend"] == "swipe"
    assert len(swipe_calls) == 1
    # Confirms coordinates come from _RECIPES["notifications"] (top-LEFT).
    x1, y1, _, _, _ = swipe_calls[0]
    assert x1 < 400   # left half of a 1440px screen


# ---------------------------------------------------------------------------
# Handler dataclass — v3.84.1 field surface
# ---------------------------------------------------------------------------
def test_mobile_handlers_dataclass_has_v84_1_fields():
    """Baseline check. Exact 38-field surface lives in test_mobile_v84_2.py."""
    from arena.mobile.handlers import MobileHandlers
    baseline = {
        "list_devices", "device_info", "screenshot", "tap", "swipe",
        "type_text", "key_event", "shell", "packages", "gesture",
        "ui_dump", "tap_by",
        "helpers_status", "helpers_install",
        "ime_status", "ime_set", "ime_reset", "paste",
        "sensors", "scroll", "key_combo",
        "pair", "connect", "disconnect", "apk_prepare", "apk_install",
        "batch",
        "camera_launch", "camera_shutter", "camera_photos",
        "camera_pull", "camera_capture",
    }
    got = {f.name for f in MobileHandlers.__dataclass_fields__.values()}
    missing = baseline - got
    assert not missing, f"v3.84.1 handlers missing: {missing}"
