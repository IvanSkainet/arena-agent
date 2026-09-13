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
import types

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
def test_live_list_windows_returns_usable_entries():
    """The part that is about the code: the list has the right shape.

    Split out of `test_live_list_windows_includes_active` (#351), which
    also demanded that some window be marked active. That second
    assertion is about the state of the desktop, not about
    `list_windows`, and it made the whole test fail whenever nothing
    held the keyboard focus.
    """
    wins = win_backend.list_windows()
    assert isinstance(wins, list)
    # Deliberately not `assert wins`. Raised in review, and correct:
    # with everything minimised or the screen locked the filtered list
    # is legitimately empty, and demanding an entry would put the same
    # desktop-state dependency back that this change removes.
    for w in wins:
        assert w["id"].isdigit()
        assert isinstance(w["title"], str)
        assert isinstance(w["active"], bool)


@_WIN_ONLY
def test_live_at_most_one_window_is_marked_active():
    """Whatever the desktop is doing, two foreground windows is a bug.

    This holds with the screen locked, with everything minimised and
    from a background process, so it is the half of the old assertion
    that was always about the code.
    """
    wins = win_backend.list_windows()
    assert len([w for w in wins if w.get("active")]) <= 1


@_WIN_ONLY
def test_live_the_filtered_list_never_keeps_a_shell_window():
    """What `visible_only=True` drops, checked against the rule spelled out.

    The expected rule is restated here as literals rather than by
    calling `_is_untitled_shell_window`. The previous version of this
    test recomputed the filter with the backend's own helper over the
    backend's own snapshot, so the two sides could not disagree and the
    assertion could never fail -- review called it a tautology and was
    right. Restating the rule is double-entry bookkeeping: the test
    fails if the backend's filter and the written-down rule diverge,
    which is the only way this can carry information.

    (In product code a second copy of a predicate is the defect #350
    was about. In a test it is the mechanism.)
    """
    for w in win_backend.list_windows():
        assert w["visible"] is True
        assert not (w["title"] == "" and w["class"] in {"Progman", "WorkerW", "Shell_TrayWnd", "IME"}), (
            f"filtered list kept a shell window: {w['class']!r}"
        )


@_WIN_ONLY
def test_live_the_unfiltered_list_does_keep_the_shell_windows():
    """The control for the test above, which otherwise passes on an
    empty list or on a filter that drops everything.

    A desktop always has a taskbar, so `visible_only=False` must show
    at least one of the classes the filtered view hides. Without this,
    "no shell window survived the filter" is satisfied by a backend
    that returns nothing at all.
    """
    everything = win_backend.list_windows(visible_only=False)
    classes = {w["class"] for w in everything}
    assert classes & {"Progman", "WorkerW", "Shell_TrayWnd", "IME"}, (
        f"no shell window in the unfiltered enumeration at all: {sorted(classes)[:20]}"
    )


@_WIN_ONLY
def test_live_the_unfiltered_view_flags_the_real_foreground_window():
    """The unfiltered enumeration must contain and flag the true HWND.

    Both halves come from one `list_windows_with_foreground()` call, so
    the flags are checked against the very value they were set from.

    Three earlier revisions of this test were tautologies -- they
    compared the returned list against itself, and `len(flagged) <= 1`
    cannot fail when a single `fg` is tested against each window. The
    revision after that bracketed the call with two
    `GetForegroundWindow()` reads and skipped when they differed, which
    review showed was still wrong: the flag is set from a third read
    inside the call, so focus that leaves and returns during the walk
    (A->B->A) leaves the outer reads agreeing while the flag holds B.

    The empty case is asserted, not skipped past. It is reachable:
    `_proc` swallows per-window exceptions, so a window that raises
    while being described drops out of the enumeration -- including the
    foreground one, which is the #351 symptom.
    """
    everything, fg = win_backend.list_windows_with_foreground(visible_only=False)
    flagged = [w["id"] for w in everything if w.get("active")]

    if not fg:
        assert flagged == []
        return
    assert flagged == [str(fg)], (
        f"foreground {fg} missing or mis-flagged in the unfiltered view"
    )


def test_the_foreground_returned_is_the_one_the_flag_was_set_from(monkeypatch):
    """Runs on every platform, unlike the live test above.

    Drives the real enumeration against a fake user32 and moves the
    foreground *during* the walk, which is the case no Windows-only
    test can stage on demand: `GetForegroundWindow` answers 111 when
    the enumeration reads it and 999 afterwards. The returned
    foreground must be the one the flags were computed from, 111, or
    the cross-check in the live test is comparing against the wrong
    number.
    """
    from arena.desktop.backends import windows as mod

    reads = []

    class _FakeUser32:
        def GetForegroundWindow(self):
            reads.append(1)
            return 111 if len(reads) == 1 else 999

        def EnumWindows(self, cb, _lparam):
            for hwnd in (111, 222):
                cb(hwnd, 0)
            return True

        def IsWindowVisible(self, hwnd):
            return 1

        def GetWindowTextLengthW(self, hwnd):
            return 5

        def GetWindowTextW(self, hwnd, buf, _n):
            buf.value = f"w{hwnd}"
            return len(buf.value)

        def GetClassNameW(self, hwnd, buf, _n):
            buf.value = "TestClass"
            return len(buf.value)

        def GetWindowThreadProcessId(self, hwnd, pid_ref):
            pid_ref._obj.value = 4242
            return 1

        def IsIconic(self, hwnd):
            return 0

    monkeypatch.setattr(mod, "_IS_WINDOWS", True)
    monkeypatch.setattr(mod, "user32", _FakeUser32())
    monkeypatch.setattr(mod, "_api", types.SimpleNamespace(EnumWindowsProc=lambda fn: fn))
    monkeypatch.setattr(mod, "_best_window_geometry", lambda hwnd, owner_pid: ({}, None, "test"))

    windows, foreground = mod.list_windows_with_foreground(visible_only=False)

    assert foreground == 111
    assert [w["id"] for w in windows if w["active"]] == ["111"]


def test_the_foreground_is_not_kept_on_the_module(monkeypatch):
    """A module-global would be shared between concurrent enumerations.

    These backend calls run under `run_in_executor`, so a second worker
    enumerating windows could overwrite a stashed snapshot between a
    caller's own call and its read -- raised in review on the previous
    revision, which did exactly that. The value is returned instead,
    and this keeps it that way.
    """
    from arena.desktop.backends import windows as mod

    stateful = [name for name in dir(mod) if "LAST_FOREGROUND" in name.upper()]
    assert stateful == []


def test_the_shell_window_filter_is_what_hides_the_foreground():
    """Runs everywhere, including CI on Linux, unlike the live tests.

    The classes dropped from `list_windows` are the whole reason the
    two views can disagree, so the rule gets a test that does not
    depend on what the operator's desktop is doing. Without this, the
    only coverage of the behaviour behind #351 is a Windows-only test
    whose branch depends on the moment it runs.
    """
    hidden = win_backend._is_untitled_shell_window
    for cls in ("Progman", "WorkerW", "Shell_TrayWnd", "IME"):
        assert hidden("", cls) is True
        assert hidden("Real title", cls) is False
    assert hidden("", "Chrome_WidgetWin_1") is False
    assert hidden("", "") is False


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
