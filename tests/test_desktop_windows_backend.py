"""Tests for the v4.81.0 Windows desktop backend.

Two kinds of tests:

1. **Platform-agnostic** — verify that ``env.py`` routes to the
   correct backend name, that ``sys.platform`` gates the
   backend module cleanly, and that
   ``arena.desktop.backends.windows`` imports on any platform
   (the ctypes bindings are guarded).

2. **Windows-only live** — skipped everywhere except native
   Windows Python. Cover the actual capture / list_windows /
   focus_window / click / type paths against real user32.

The live tests are the ones that give us the "yes it works on
the operator's box" signal; the platform-agnostic tests are
what we run in CI on Linux to prevent regressions in the
router.
"""
from __future__ import annotations

import sys

import pytest

# The Windows backend module MUST import on any platform, so the
# router can do `from arena.desktop.backends import windows` safely.
from arena.desktop.backends import windows as win_backend


def test_backend_module_imports_on_any_platform():
    """The module always imports; is_available() gates the calls."""
    assert hasattr(win_backend, "is_available")
    assert win_backend.is_available() is (sys.platform == "win32")


def test_env_reports_windows_flags_on_windows(monkeypatch):
    """``_detect_desktop_env`` sets the has_win32_* flags iff on Windows."""
    from arena.desktop.env import _detect_desktop_env
    monkeypatch.setattr("arena.desktop.env.sys.platform", "win32")
    env = _detect_desktop_env()
    assert env["session_type"] == "windows"
    assert env["windows"] is True
    assert env["has_win32_screenshot"] is True
    assert env["has_win32_input"] is True
    assert env["has_win32_windows"] is True
    # Linux flags stay False so the linux dispatch short-circuits.
    assert env["has_spectacle"] is False
    assert env["has_grim"] is False
    assert env["has_ydotool"] is False


def test_env_reports_linux_flags_on_non_windows(monkeypatch):
    """On non-Windows, the has_win32_* flags stay False."""
    from arena.desktop.env import _detect_desktop_env
    monkeypatch.setattr("arena.desktop.env.sys.platform", "linux")
    env = _detect_desktop_env()
    assert env["windows"] is False
    assert env["has_win32_screenshot"] is False
    assert env["has_win32_input"] is False
    assert env["has_win32_windows"] is False


def test_stub_calls_raise_notimplementederror_on_non_windows():
    """Every public callable raises NotImplementedError on non-Windows."""
    if sys.platform == "win32":
        pytest.skip("Windows-live path tested separately")
    for name in (
        "virtual_screen_rect",
        "get_active_window",
    ):
        fn = getattr(win_backend, name)
        with pytest.raises(NotImplementedError):
            fn()
    with pytest.raises(NotImplementedError):
        win_backend.capture_screenshot()
    with pytest.raises(NotImplementedError):
        win_backend.list_windows()
    with pytest.raises(NotImplementedError):
        win_backend.find_main_window_for_pid(123)
    with pytest.raises(NotImplementedError):
        win_backend.find_window_by_title("x")
    with pytest.raises(NotImplementedError):
        win_backend.focus_window(0)
    with pytest.raises(NotImplementedError):
        win_backend.move_window(0, 0, 0, 100, 100)
    with pytest.raises(NotImplementedError):
        win_backend.click(0, 0)
    with pytest.raises(NotImplementedError):
        win_backend.mouse_move(0, 0)
    with pytest.raises(NotImplementedError):
        win_backend.cursor_position()
    with pytest.raises(NotImplementedError):
        win_backend.type_text("x")
    with pytest.raises(NotImplementedError):
        win_backend.key("a")


def test_bmp_fallback_encoder_produces_valid_bmp():
    """Even without Pillow, `_raw_bgra_to_bmp` yields a syntactically valid BMP.

    This exercises the pure-Python fallback path used when Pillow
    isn't installed. We construct a 2x2 red rectangle in BGRA and
    check the resulting bytes start with the BMP magic + report
    the right file size in the header.
    """
    # 2x2 red: B=0, G=0, R=255, A=0 per pixel, 4 pixels, 16 bytes total
    pixels = b"\x00\x00\xff\x00" * 4
    bmp = win_backend._raw_bgra_to_bmp(pixels, 2, 2)
    assert bmp[:2] == b"BM"
    reported_size = int.from_bytes(bmp[2:6], "little")
    assert reported_size == len(bmp), "BITMAPFILEHEADER file size mismatch"
    # BITMAPINFOHEADER width @ offset 18 is 4 bytes little-endian
    assert int.from_bytes(bmp[18:22], "little") == 2
    # height is negative (top-down)
    height = int.from_bytes(bmp[22:26], "little", signed=True)
    assert height == -2


def test_vk_map_is_lowercase_and_covers_common_keys():
    """Regression guard for the virtual-key alias table."""
    if sys.platform != "win32":
        pytest.skip("VK_MAP is only populated on Windows")
    for name in ("enter", "escape", "tab", "f1", "ctrl", "shift", "alt"):
        assert name in win_backend.VK_MAP
    # All keys are lowercase (the ``key()`` API lowercases before lookup).
    for k in win_backend.VK_MAP:
        assert k == k.lower(), f"non-lowercase key {k!r}"


def test_select_best_visual_child_prefers_largest_visible_positive_geometry():
    candidates = [
        {"id": "zero", "visible": True, "geometry": {"x": 0, "y": 0, "width": 1000, "height": 0}},
        {"id": "hidden", "visible": False, "geometry": {"x": 0, "y": 0, "width": 2000, "height": 1000}},
        {"id": "small", "visible": True, "geometry": {"x": 10, "y": 10, "width": 100, "height": 100}},
        {"id": "large", "visible": True, "title": "Main", "geometry": {"x": 20, "y": 20, "width": 1000, "height": 700}},
    ]
    assert win_backend._select_best_visual_child(candidates)["id"] == "large"


def test_geometry_area_rejects_zero_height():
    assert win_backend._geometry_area({"x": 20, "y": 20, "width": 985, "height": 0}) == 0
    assert win_backend._geometry_area({"x": 20, "y": 20, "width": 985, "height": 700}) == 689500


# ---------------------------------------------------------------------------
# Windows-only live tests
# ---------------------------------------------------------------------------
_WIN_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows")


@_WIN_ONLY
def test_live_virtual_screen_rect_is_sensible():
    x, y, w, h = win_backend.virtual_screen_rect()
    assert isinstance(w, int) and w > 0
    assert isinstance(h, int) and h > 0
    # x/y can be negative on multi-monitor layouts; just check they're ints
    assert isinstance(x, int)
    assert isinstance(y, int)


@_WIN_ONLY
def test_live_capture_screenshot_returns_bytes():
    data = win_backend.capture_screenshot()
    assert isinstance(data, bytes)
    assert len(data) > 100  # even the smallest PNG/BMP is > 100 bytes


@_WIN_ONLY
def test_live_list_windows_includes_active():
    wins = win_backend.list_windows()
    assert isinstance(wins, list)
    assert any(w.get("active") for w in wins)


@_WIN_ONLY
def test_live_get_active_window_has_id_and_title():
    w = win_backend.get_active_window()
    assert w is not None
    assert "id" in w


@_WIN_ONLY
def test_live_cursor_move_and_read_roundtrip():
    win_backend.mouse_move(500, 500)
    x, y = win_backend.cursor_position()
    # Some Windows configurations move the cursor to the nearest
    # legal position, so we tolerate a small delta.
    assert abs(x - 500) < 5
    assert abs(y - 500) < 5


@_WIN_ONLY
def test_live_find_window_by_title_returns_none_for_garbage():
    assert win_backend.find_window_by_title("__no_such_window_v4810__") is None
