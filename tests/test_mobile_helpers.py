"""Tests for v3.83.2 additions: rotation, screenshot source dims, and helpers.

Kept separate from tests/test_mobile.py so both files stay under the
600-line runtime cap without squeezing whitespace.
"""
from __future__ import annotations

from arena.mobile import adb as _adb  # noqa: F401 — kept for parity
from arena.mobile import devices as _dev  # noqa: F401
from arena.mobile import helpers as _h  # noqa: F401
from arena.mobile import input as _input  # noqa: F401
from arena.mobile import screenshot as _s  # noqa: F401


# ---------------------------------------------------------------------------
# v3.83.2 — rotation awareness, source-dimension headers, helpers module
# ---------------------------------------------------------------------------
def test_screen_probe_reports_rotation_and_current_size(monkeypatch):
    """dumpsys window displays gives `cur=WxH` in the currently-rotated
    orientation. dumpsys input gives `orientation=N` in the INTERNAL
    viewport line. Both must land in the returned dict."""
    from arena.mobile import devices as _dev
    wm_size = "Physical size: 1440x3200\n"
    wm_density = "Physical density: 600\n"
    disp = (
        "  Display: mDisplayId=0 (organized)\n"
        "    init=1440x3200 600dpi mMinSizeOfResizeableTaskDp=200\n"
        "    cur=3200x1440 app=3200x1440 rng=1440x1440-3200x3200\n"
    )
    inp = (
        "        Orientation: Rotation0\n"
        "      Viewport INTERNAL: displayId=0, uniqueId=local:xxx, port=131, "
        "orientation=1, logicalFrame=[0, 0, 3200, 1440], physicalFrame=[0, 0, 3200, 1440]\n"
    )
    def _fake_sh(serial, args, timeout=5):
        if args[:2] == ["wm", "size"]: return wm_size.strip()
        if args[:2] == ["wm", "density"]: return wm_density.strip()
        if args[:2] == ["dumpsys", "window"]: return disp
        if args[:2] == ["dumpsys", "input"]: return inp
        return ""
    monkeypatch.setattr(_dev, "_sh", _fake_sh)
    out = _dev._probe_screen("dummy")
    assert out.get("screen_size_physical") == "1440x3200"
    assert out.get("screen_size_current") == "3200x1440"
    assert out.get("rotation") == 1
    assert out.get("orientation") == "landscape"
    assert out.get("density_physical") == "600"


def test_screenshot_returns_source_dims_for_rotation_aware_scaling():
    """capture()'s dict must expose `source_width`/`source_height` (the
    native rotated pixels) alongside the possibly-downscaled width/height."""
    from arena.mobile import screenshot as _s
    from arena.mobile import adb as _adb2
    fake_png = (
        b"\x89PNG\r\n\x1a\n"           # signature
        b"\x00\x00\x00\rIHDR"          # length + type
        b"\x00\x00\x0c\x80"            # width = 3200 (landscape!)
        b"\x00\x00\x05\xa0"            # height = 1440
        b"\x08\x02\x00\x00\x00"        # bit depth, color, ...
    )
    class _Result:
        def __init__(self):
            self.returncode = 0
            self.stdout = fake_png
            self.stderr = b""
    orig_find = _s.find_adb
    orig_run = _s.run
    _s.find_adb = lambda: "/usr/bin/adb"
    _s.run = lambda *a, **kw: _Result()
    try:
        r = _s.capture("dummy")
    finally:
        _s.find_adb = orig_find
        _s.run = orig_run
    assert r["ok"] is True
    assert r["width"] == 3200 and r["height"] == 1440
    assert r["source_width"] == 3200 and r["source_height"] == 1440


# ---------------------------------------------------------------------------
# helpers.py — bundled APK metadata, consent token, IME state, paste
# ---------------------------------------------------------------------------
def test_helpers_bundled_apk_status_missing_file_is_actionable(tmp_path, monkeypatch):
    """When the APK isn't shipped in this build, status() must fail
    with a hint pointing at the expected location — not a bare
    FileNotFoundError from open()."""
    from arena.mobile import helpers as _h
    monkeypatch.setattr(_h, "bundled_apk_path",
                        lambda: tmp_path / "does-not-exist.apk")
    r = _h.bundled_apk_status()
    assert r["ok"] is False
    assert "not present" in r["error"]
    assert "does-not-exist.apk" in r["hint"]
    assert r["expected_sha256"] == _h.ADBKEYBOARD_SHA256


def test_helpers_bundled_apk_status_hash_mismatch_refuses(tmp_path, monkeypatch):
    """Someone swapping the bundled APK for a different one must be
    caught by the SHA-256 guard, not silently trusted."""
    from arena.mobile import helpers as _h
    fake = tmp_path / "fake.apk"
    fake.write_bytes(b"not a real apk at all")
    monkeypatch.setattr(_h, "bundled_apk_path", lambda: fake)
    r = _h.bundled_apk_status()
    assert r["ok"] is False
    assert "hash mismatch" in r["error"]
    assert r["hash_matches"] is False


def test_helpers_consent_token_is_apk_specific():
    """The consent token must include a prefix of the APK's own hash,
    so rotating the bundle invalidates stale prompts."""
    from arena.mobile.helpers import _consent_token, ADBKEYBOARD_SHA256
    tok = _consent_token(ADBKEYBOARD_SHA256)
    assert tok.startswith("yes-install-adbkeyboard-")
    assert tok.endswith(ADBKEYBOARD_SHA256[:8])
    other = _consent_token("00" * 32)
    assert other != tok


def test_helpers_install_rejects_wrong_consent(tmp_path, monkeypatch):
    from arena.mobile import helpers as _h
    monkeypatch.setattr(_h, "bundled_apk_status", lambda: {
        "ok": True, "sha256": _h.ADBKEYBOARD_SHA256,
        "path": "/tmp/x.apk", "size_bytes": 100,
        "version": _h.ADBKEYBOARD_VERSION,
    })
    r = _h.install_adbkeyboard("dummy", consent="oops-wrong")
    assert r["ok"] is False
    assert "consent" in r["error"]
    assert r["required_consent"].startswith("yes-install-adbkeyboard-")


def test_helpers_paste_refuses_without_adbkeyboard(monkeypatch):
    """paste_text must fail with an actionable hint when ADBKeyboard
    is not installed — not silently broadcast to nowhere."""
    from arena.mobile import helpers as _h
    monkeypatch.setattr(_h, "find_adb", lambda: "/usr/bin/adb")
    monkeypatch.setattr(_h, "ime_status", lambda serial: {
        "ok": True,
        "adbkeyboard_installed": False,
        "adbkeyboard_active": False,
        "current": "com.google.android.inputmethod.latin/...",
    })
    r = _h.paste_text("dummy", "привет")
    assert r["ok"] is False
    assert "not installed" in r["error"]
    assert "helpers/install" in r["hint"]


def test_helpers_paste_refuses_when_installed_but_inactive(monkeypatch):
    from arena.mobile import helpers as _h
    monkeypatch.setattr(_h, "find_adb", lambda: "/usr/bin/adb")
    monkeypatch.setattr(_h, "ime_status", lambda serial: {
        "ok": True,
        "adbkeyboard_installed": True,
        "adbkeyboard_active": False,
        "current": "com.google.android.inputmethod.latin/...",
    })
    r = _h.paste_text("dummy", "привет")
    assert r["ok"] is False
    assert "not the active IME" in r["error"]
    assert "helpers/ime_set" in r["hint"]
    assert r["current_ime"].startswith("com.google.android.inputmethod")


def test_helpers_paste_base64_encodes_utf8(monkeypatch):
    """Happy path: with ADBKeyboard active, paste_text base64-encodes
    the utf-8 bytes and issues the broadcast."""
    import base64
    from arena.mobile import helpers as _h
    monkeypatch.setattr(_h, "find_adb", lambda: "/usr/bin/adb")
    monkeypatch.setattr(_h, "ime_status", lambda serial: {
        "ok": True, "adbkeyboard_installed": True, "adbkeyboard_active": True,
        "current": _h.ADBKEYBOARD_SERVICE,
    })
    captured: dict = {}
    class _R:
        returncode = 0
        stdout = "Broadcast completed: result=0\n"
        stderr = ""
    def _fake_run(args, serial=None, timeout=10):
        captured["args"] = args
        return _R()
    monkeypatch.setattr(_h, "run", _fake_run)
    r = _h.paste_text("dummy", "привет 🌍")
    assert r["ok"] is True
    assert r["chars"] == 8
    # Verify the payload the broadcast carried is base64(utf-8("привет 🌍"))
    args = captured["args"]
    idx = args.index("msg")
    encoded = args[idx + 1]
    assert base64.b64decode(encoded).decode("utf-8") == "привет 🌍"


def test_helpers_ime_status_shape(monkeypatch):
    from arena.mobile import helpers as _h
    monkeypatch.setattr(_h, "find_adb", lambda: "/usr/bin/adb")
    def _fake_run_sh(serial, args, timeout=6):
        if args[:3] == ["settings", "get", "secure"]:
            return _h.ADBKEYBOARD_SERVICE
        if args[:2] == ["ime", "list"] and "-a" in args:
            return (
                _h.ADBKEYBOARD_SERVICE + "\n"
                "com.google.android.inputmethod.latin/.LatinIME\n"
            )
        if args[:2] == ["ime", "list"]:
            return _h.ADBKEYBOARD_SERVICE + "\n"
        return ""
    monkeypatch.setattr(_h, "_run_sh", _fake_run_sh)
    r = _h.ime_status("dummy")
    assert r["ok"] is True
    assert r["current"] == _h.ADBKEYBOARD_SERVICE
    assert r["adbkeyboard_installed"] is True
    assert r["adbkeyboard_enabled"] is True
    assert r["adbkeyboard_active"] is True
