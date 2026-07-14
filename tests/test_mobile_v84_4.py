"""Tests for v3.84.4: full camera control surface.

Covers pure-Python parts that do not need a live device:
  * shutter detector regression -- v9_capture_picker_layout must not
    win over shutter_button any more
  * mode / lens / zoom / flash alias resolution
  * shutter cache fallback for record_stop when uiautomator dumps blank
  * exact 49-field handler dataclass surface (was 42 in v3.84.3)

Autouse fixture below fakes `adb` presence on every test so CI runners
(which don't have adb installed) don't short-circuit inside
`_ensure_adb`. Individual tests still monkeypatch subprocess-level
helpers where they need to."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _fake_adb_available(monkeypatch):
    """Every entry point in arena.mobile.camera[_controls] calls
    `_ensure_adb()` first, which returns an error dict when
    `find_adb()` returns None (the case on CI). Pretend adb is
    installed for every test in this file."""
    import arena.mobile.adb as _adb
    import arena.mobile.camera as _cam
    monkeypatch.setattr(_adb, "find_adb", lambda: "/fake/adb")
    monkeypatch.setattr(_cam, "find_adb", lambda: "/fake/adb")
    yield


# ---------------------------------------------------------------------------
# Shutter detector regression: v9_capture_picker_layout must not win.
# ---------------------------------------------------------------------------
def _fake_dump(nodes):
    return {"ok": True, "package": "com.android.camera",
            "screen_bounds": [1440, 3200], "nodes": nodes}


def test_find_shutter_prefers_shutter_button_over_capture_picker(monkeypatch):
    """Reproduction of the v3.84.3 bug: on HyperOS the mode switcher
    (`v9_capture_picker_layout`, ends in `capture` + `picker`) beat
    the real `shutter_button` because both matched a `capture` hint."""
    from arena.mobile import camera as _c
    nodes = [
        {"resource-id": "com.android.camera:id/shutter_button",
         "clickable": "true", "center": [719, 2785],
         "width": 341, "height": 341,
         "content-desc": "Кнопка затвора", "text": ""},
        {"resource-id": "com.android.camera:id/v9_capture_picker_layout",
         "clickable": "true", "center": [1300, 2785],
         "width": 161, "height": 161,
         "content-desc": "", "text": ""},
        {"resource-id": "com.android.camera:id/v9_smart_shutter_button_layout",
         "clickable": "false", "center": [170, 170],
         "width": 341, "height": 341, "content-desc": "", "text": ""},
    ]
    monkeypatch.setattr(_c, "iter_clickable",
                        lambda serial: (_fake_dump(nodes),
                                        [n for n in nodes if n["clickable"] == "true"]))
    r = _c.find_shutter("dummy")
    assert r["ok"] is True
    assert (r["x"], r["y"]) == (719, 2785)
    assert "shutter_button" in r["source"]
    assert "picker" not in r["resource_id"]


def test_find_shutter_ignores_blacklisted_ids(monkeypatch):
    """Nodes whose resource-id contains blacklisted substrings
    (picker/thumbnail/menu/etc) must never be chosen."""
    from arena.mobile import camera as _c
    nodes = [
        {"resource-id": "com.android.camera:id/thumbnail_container",
         "clickable": "true", "center": [146, 2785],
         "width": 150, "height": 150,
         "content-desc": "shutter",  # tricky: desc hints as shutter
         "text": ""},
    ]
    monkeypatch.setattr(_c, "iter_clickable",
                        lambda s: (_fake_dump(nodes), nodes))
    r = _c.find_shutter("dummy")
    # Since the only candidate is blacklisted, we should fall through
    # all three passes and return not-ok.
    assert r["ok"] is False


def test_find_shutter_falls_back_to_bottom_center_quarter(monkeypatch):
    """Unknown ROM: no known resource-id, but a clickable node sits in
    the bottom-center quarter -- pick it."""
    from arena.mobile import camera as _c
    nodes = [
        {"resource-id": "com.example.newrom:id/big_button",
         "clickable": "true", "center": [720, 2900],
         "width": 400, "height": 400, "content-desc": "", "text": ""},
    ]
    monkeypatch.setattr(_c, "iter_clickable",
                        lambda s: (_fake_dump(nodes), nodes))
    r = _c.find_shutter("dummy")
    assert r["ok"] is True
    assert r["x"] == 720
    assert "bottom-center" in r["source"]


# ---------------------------------------------------------------------------
# Alias resolution
# ---------------------------------------------------------------------------
def test_mode_alias_resolves_english_russian_and_canonical():
    from arena.mobile import camera_controls as cc
    for key in ("video", "Video", "Видео", "VIDEO"):
        r = cc._resolve_alias(key, cc._MODE_ALIASES)
        assert r is not None
        assert r[0] == "video"
    assert cc._resolve_alias("teleport", cc._MODE_ALIASES) is None


def test_flash_alias_covers_localized_labels():
    from arena.mobile import camera_controls as cc
    assert cc._resolve_alias("Авто", cc._FLASH_ALIASES)[0] == "auto"
    assert cc._resolve_alias("torch", cc._FLASH_ALIASES)[0] == "torch"


# ---------------------------------------------------------------------------
# Shutter cache fallback (fixes "blank uiautomator dump" during recording)
# ---------------------------------------------------------------------------
def test_shutter_cache_recall_after_ttl(monkeypatch):
    from arena.mobile import camera_controls as cc
    cc._SHUTTER_CACHE.clear()
    cc._remember_shutter("dev", 719, 2785)
    assert cc._recall_shutter("dev") == (719, 2785)
    # Force TTL expiry.
    x, y, ts = cc._SHUTTER_CACHE["dev"]
    cc._SHUTTER_CACHE["dev"] = (x, y, ts - cc._SHUTTER_CACHE_TTL_SEC - 1)
    assert cc._recall_shutter("dev") is None
    assert "dev" not in cc._SHUTTER_CACHE


def test_shutter_tap_falls_back_to_cache_when_live_detect_fails(monkeypatch):
    from arena.mobile import camera as cam
    from arena.mobile import camera_controls as cc
    cc._SHUTTER_CACHE.clear()
    cc._remember_shutter("dev", 719, 2785)

    def _fake_live_shutter(serial):
        return {"ok": False, "error": "uiautomator returned no XML"}

    tapped = {}

    def _fake_tap(serial, x, y):
        tapped["xy"] = (x, y)
        return {"ok": True}

    monkeypatch.setattr(cam, "shutter", _fake_live_shutter)
    monkeypatch.setattr(cc, "_tap", _fake_tap)
    r = cc._shutter_tap("dev")
    assert r["ok"] is True
    assert (r["shutter_x"], r["shutter_y"]) == (719, 2785)
    assert "cached" in r["detected_via"]
    assert tapped["xy"] == (719, 2785)


def test_shutter_tap_returns_live_error_when_no_cache(monkeypatch):
    from arena.mobile import camera as cam
    from arena.mobile import camera_controls as cc
    cc._SHUTTER_CACHE.clear()

    def _fake_live_shutter(serial):
        return {"ok": False, "error": "uiautomator returned no XML"}

    monkeypatch.setattr(cam, "shutter", _fake_live_shutter)
    r = cc._shutter_tap("dev")
    assert r["ok"] is False
    assert "no XML" in r["error"]


# ---------------------------------------------------------------------------
# switch_mode: fuzzy label matching across text vs content-desc.
# ---------------------------------------------------------------------------
def test_switch_mode_taps_matching_mode_select_item(monkeypatch):
    from arena.mobile import camera as cam
    from arena.mobile import camera_controls as cc
    nodes = [
        {"resource-id": "com.android.camera:id/mode_select_item",
         "text": "Видео", "content-desc": "", "center": [450, 2504]},
        {"resource-id": "com.android.camera:id/mode_select_item",
         "text": "Фото", "content-desc": "", "center": [720, 2504]},
    ]
    monkeypatch.setattr(cam, "iter_clickable",
                        lambda s: (_fake_dump(nodes), []))
    tapped = {}

    def _tap_stub(serial, x, y):
        tapped["xy"] = (x, y)
        return {"ok": True}

    monkeypatch.setattr(cc, "_tap", _tap_stub)
    r = cc.switch_mode("dev", "video")
    assert r["ok"] is True
    assert r["mode"] == "video"
    assert r["matched_label"] == "Видео"
    assert tapped["xy"] == (450, 2504)


def test_switch_mode_rejects_unknown_mode():
    from arena.mobile import camera_controls as cc
    r = cc.switch_mode("dev", "hologram")
    assert r["ok"] is False
    assert "unknown mode" in r["error"]


# ---------------------------------------------------------------------------
# list_controls warms the shutter cache.
# ---------------------------------------------------------------------------
def test_list_controls_warms_shutter_cache(monkeypatch):
    from arena.mobile import camera as cam
    from arena.mobile import camera_controls as cc
    cc._SHUTTER_CACHE.clear()
    clickable = [
        {"resource-id": "com.android.camera:id/shutter_button",
         "clickable": "true",
         "center": [719, 2785], "bounds": "[549,2615][890,2956]",
         "content-desc": "Кнопка затвора", "text": "", "class": "android.view.View"},
    ]
    monkeypatch.setattr(cam, "iter_clickable",
                        lambda s: (_fake_dump(clickable), clickable))
    r = cc.list_controls("dev")
    assert r["ok"] is True
    assert r["count"] == 1
    assert r["cached_shutter"] == (719, 2785)


# ---------------------------------------------------------------------------
# switch_lens content-desc round-trip.
# ---------------------------------------------------------------------------
def test_switch_lens_reports_already_when_on_target(monkeypatch):
    from arena.mobile import camera as cam
    from arena.mobile import camera_controls as cc
    nodes = [
        {"resource-id": "com.android.camera:id/v9_camera_picker",
         "content-desc": "Переключение камеры,Задний",
         "center": [1300, 2785]},
    ]
    monkeypatch.setattr(cam, "iter_clickable",
                        lambda s: (_fake_dump(nodes), nodes))
    r = cc.switch_lens("dev", "back")
    assert r["ok"] is True
    assert r["already"] == "back"


def test_switch_lens_taps_when_target_differs(monkeypatch):
    from arena.mobile import camera as cam
    from arena.mobile import camera_controls as cc
    nodes = [
        {"resource-id": "com.android.camera:id/v9_camera_picker",
         "content-desc": "Переключение камеры,Задний",
         "center": [1300, 2785]},
    ]
    monkeypatch.setattr(cam, "iter_clickable",
                        lambda s: (_fake_dump(nodes), nodes))
    tapped = {}

    def _tap_stub(serial, x, y):
        tapped["xy"] = (x, y)
        return {"ok": True}

    monkeypatch.setattr(cc, "_tap", _tap_stub)
    r = cc.switch_lens("dev", "front")
    assert r["ok"] is True
    assert r["was"] == "back"
    assert tapped["xy"] == (1300, 2785)


# ---------------------------------------------------------------------------
# zoom finds the chip closest to the requested level.
# ---------------------------------------------------------------------------
def test_set_zoom_picks_closest_zoom_chip(monkeypatch):
    from arena.mobile import camera as cam
    from arena.mobile import camera_controls as cc
    # Include a red-herring node whose desc has "3" but no zoom in
    # rid/desc -- must be ignored.
    nodes = [
        {"resource-id": "com.android.camera:id/zoom_toggle_button",
         "content-desc": "Приближение 0.6X", "text": "",
         "center": [538, 2284]},
        {"resource-id": "com.android.camera:id/zoom_toggle_button",
         "content-desc": "Приближение 1.0X", "text": "",
         "center": [718, 2284]},
        {"resource-id": "com.android.camera:id/zoom_toggle_button",
         "content-desc": "Приближение 2.0X", "text": "",
         "center": [899, 2284]},
        {"resource-id": "com.android.camera:id/menu_indicator",
         "content-desc": "3 items", "text": "",
         "center": [800, 285]},
    ]
    monkeypatch.setattr(cam, "iter_clickable",
                        lambda s: (_fake_dump(nodes), []))
    tapped = {}

    def _tap_stub(serial, x, y):
        tapped["xy"] = (x, y)
        return {"ok": True}

    monkeypatch.setattr(cc, "_tap", _tap_stub)
    r = cc.set_zoom("dev", 2.0)
    assert r["ok"] is True
    assert r["matched"] == 2.0
    assert tapped["xy"] == (899, 2284)


# ---------------------------------------------------------------------------
# Handler dataclass — v3.84.4 exact 49-field surface.
# ---------------------------------------------------------------------------
def test_mobile_handlers_dataclass_fields_v84_4():
    from arena.mobile.handlers import MobileHandlers
    expected = {
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
        "apk_upload",
        "record_sync", "record_start", "record_stop",
        "record_list", "record_pull", "record_purge",
        "mirror_ws", "mirror_stats", "mirror_stop",
        # v3.84.4 additions.
        "camera_controls", "camera_mode", "camera_lens",
        "camera_zoom", "camera_flash",
        "camera_record_start", "camera_record_stop",
    }
    got = {f.name for f in MobileHandlers.__dataclass_fields__.values()}
    assert expected == got, (
        f"MobileHandlers drift: extra={got - expected}, "
        f"missing={expected - got}"
    )
    assert len(got) == 49


# ---------------------------------------------------------------------------
# Video pull path in camera.pull_photo bypasses PIL and picks the right mime.
# ---------------------------------------------------------------------------
def test_pull_photo_video_mp4_bypasses_pil(monkeypatch):
    from arena.mobile import camera as cam

    class _FakeRes:
        returncode = 0
        stdout = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32
        stderr = b""

    def _fake_run(argv, serial=None, timeout=60, capture_binary=False):
        return _FakeRes()

    monkeypatch.setattr(cam, "run", _fake_run)
    monkeypatch.setattr(cam, "find_adb", lambda: "/fake/adb")
    r = cam.pull_photo("dev", "/sdcard/DCIM/Camera/VID_x.mp4")
    assert r["ok"] is True
    assert r["mime"] == "video/mp4"
    assert r["bytes_b64"]  # base64-encoded payload


def test_newest_video_ignores_jpeg_stills(monkeypatch):
    """record_stop must lock onto the freshest .mp4/.mov, not a
    MotionPhoto still that happens to have a newer mtime -- otherwise
    the caller sees a JPEG as `video_path` in the response."""
    from arena.mobile import camera as cam
    from arena.mobile import camera_controls as cc

    listing = {
        "ok": True, "count": 3,
        "photos": [
            {"path": "/sdcard/DCIM/Camera/MVIMG_20260715.jpg",
             "name": "MVIMG_20260715.jpg",
             "size_bytes": 16_206_218,
             "modified": "2026-07-15 02:00"},
            {"path": "/sdcard/DCIM/Camera/VID_20260715_015927.mp4",
             "name": "VID_20260715_015927.mp4",
             "size_bytes": 831_193_715,
             "modified": "2026-07-15 02:01"},
            {"path": "/sdcard/DCIM/Camera/IMG_20260714.jpg",
             "name": "IMG_20260714.jpg",
             "size_bytes": 3_965_833,
             "modified": "2026-07-14 22:39"},
        ],
    }
    monkeypatch.setattr(cam, "list_photos", lambda serial, limit=10: listing)
    monkeypatch.setattr(cam, "photo_mtime", lambda serial, path: 42.0)
    path, mtime = cc._newest_video("dev")
    assert path == "/sdcard/DCIM/Camera/VID_20260715_015927.mp4"
    assert mtime == 42.0


def test_newest_video_returns_none_when_no_video_present(monkeypatch):
    from arena.mobile import camera as cam
    from arena.mobile import camera_controls as cc
    listing = {"ok": True, "count": 1,
               "photos": [{"path": "/sdcard/DCIM/Camera/IMG_x.jpg",
                           "name": "IMG_x.jpg", "size_bytes": 1_000,
                           "modified": "2026-07-15 02:00"}]}
    monkeypatch.setattr(cam, "list_photos", lambda serial, limit=10: listing)
    monkeypatch.setattr(cam, "photo_mtime", lambda serial, path: 0.0)
    path, mtime = cc._newest_video("dev")
    assert path is None and mtime == 0.0


def test_camera_launch_video_intent_maps_correctly(monkeypatch):
    from arena.mobile import camera as cam

    def _fake_sh(serial, args, timeout=10):
        assert "android.media.action.VIDEO_CAMERA" in args
        return (0, "Starting: Intent { }", "")

    monkeypatch.setattr(cam, "_sh", _fake_sh)
    monkeypatch.setattr(cam, "find_adb", lambda: "/fake/adb")
    r = cam.launch("dev", intent="video")
    assert r["ok"] is True
    assert r["intent"] == "android.media.action.VIDEO_CAMERA"
