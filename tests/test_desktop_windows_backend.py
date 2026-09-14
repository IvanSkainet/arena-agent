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
def test_live_the_filter_removes_windows_rather_than_finding_none():
    """The control for the test above, which otherwise passes on an
    empty list or on a filter that drops everything.

    An earlier version demanded that `visible_only=False` show one of
    the shell classes. Review pointed out that this asserts a property
    of the host, not of the backend: Server Core has no Explorer, and
    Shell Launcher can replace it, so enumeration could be perfectly
    correct and the test still fail. The deterministic fake covers
    "unfiltered keeps shell windows" without needing a taskbar.

    What is left is the part that is genuinely about this code: the
    filtered view is a subset of the unfiltered one, and enumeration
    returned something to filter in the first place. That is what makes
    "no shell window survived the filter" carry information.
    """
    everything = win_backend.list_windows(visible_only=False)
    filtered = win_backend.list_windows(visible_only=True)

    assert everything, "unfiltered enumeration returned nothing at all"
    assert len(filtered) <= len(everything)
    unfiltered_classes = {w["class"] for w in everything}
    for w in filtered:
        assert w["class"] in unfiltered_classes, (
            f"filtered view invented a window the unfiltered walk never saw: {w['class']!r}"
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
    # Not `flagged == [str(fg)]`: the foreground window can close, or
    # fail to be described, between the snapshot and the walk reaching
    # it, and then it is legitimately absent -- the docstring above
    # already says that path is reachable. Raised in review. What must
    # never happen is a *different* window wearing the flag, and that
    # is what this still catches; the deterministic test pins identity.
    assert flagged in ([], [str(fg)]), (
        f"a window other than foreground {fg} was flagged active: {flagged}"
    )


def test_the_foreground_returned_is_the_one_the_flag_was_set_from(monkeypatch):
    """Runs on every platform, unlike the live test above.

    The fake answers 111 when `_enumerate_windows` reads the foreground
    at the top, then flips to 999 inside `EnumWindows`, before the
    window holding the focus is described. A correct implementation
    reads the value once, so both the flags and the returned value say
    111; one that re-reads it -- on return, or per window -- sees 999
    and this fails.

    The previous version of this test claimed to do that and did not:
    the fake's second answer was never reached, so both assertions came
    from the same single local and passed by construction. Review
    called it the milder form of the tautology this PR removes, which
    it was.
    """
    from arena.desktop.backends import _win32_windows as mod

    state = {"fg": 111}

    class _FakeUser32:
        def GetForegroundWindow(self):
            return state["fg"]

        def EnumWindows(self, cb, _lparam):
            # Focus moves away before the window that holds it is
            # described, so an implementation that re-reads the
            # foreground per window flags nothing, while one that read
            # it once still flags 111.
            state["fg"] = 999
            cb(111, 0)
            cb(222, 0)
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

    assert state["fg"] == 999, "the fake did not actually move the foreground"
    assert foreground == 111
    assert [w["id"] for w in windows if w["active"]] == ["111"]


def _fake_user32_listing(windows, *, foreground=0, hidden=()):
    """A user32 stand-in enumerating `windows` as (hwnd, title, class)."""

    class _Fake:
        def GetForegroundWindow(self):
            return foreground

        def EnumWindows(self, cb, _lparam):
            for hwnd, _title, _cls in windows:
                cb(hwnd, 0)
            return True

        def IsWindowVisible(self, hwnd):
            return 0 if hwnd in hidden else 1

        def GetWindowTextLengthW(self, hwnd):
            return len(dict((h, t) for h, t, _c in windows)[hwnd])

        def GetWindowTextW(self, hwnd, buf, _n):
            buf.value = dict((h, t) for h, t, _c in windows)[hwnd]
            return len(buf.value)

        def GetClassNameW(self, hwnd, buf, _n):
            buf.value = dict((h, c) for h, _t, c in windows)[hwnd]
            return len(buf.value)

        def GetWindowThreadProcessId(self, hwnd, pid_ref):
            pid_ref._obj.value = 4242
            return 1

        def IsIconic(self, hwnd):
            return 0

    return _Fake()


def test_the_filtered_listing_drops_shell_windows_on_every_platform(monkeypatch):
    """The filter is applied by `list_windows`, not merely defined.

    `_is_untitled_shell_window` having the right answer means nothing
    if the enumeration stops consulting it, and the only thing covering
    that was a Windows-only live test. Caught by mutation: deleting the
    `visible_only and` guard in `_describe_window` left every test
    green.
    """
    from arena.desktop.backends import _win32_windows as mod

    listing = [
        (111, "", "Shell_TrayWnd"),
        (222, "Real window", "Chrome_WidgetWin_1"),
        (333, "", "Progman"),
        (444, "Titled tray", "Shell_TrayWnd"),
    ]
    monkeypatch.setattr(mod, "_IS_WINDOWS", True)
    monkeypatch.setattr(mod, "user32", _fake_user32_listing(listing))
    monkeypatch.setattr(mod, "_api", types.SimpleNamespace(EnumWindowsProc=lambda fn: fn))
    monkeypatch.setattr(mod, "_best_window_geometry", lambda hwnd, owner_pid: ({}, None, "test"))

    assert [w["id"] for w in mod.list_windows()] == ["222", "444"]
    # Unfiltered keeps them all, or the assertion above is satisfied by
    # an enumeration that simply lost the windows.
    assert [w["id"] for w in mod.list_windows(visible_only=False)] == ["111", "222", "333", "444"]


def test_the_filtered_listing_drops_invisible_windows(monkeypatch):
    """The other half of `visible_only`, also Windows-only until now.

    Same mutation argument as the shell-class filter: removing the
    `visible_only and not visible` guard left every test green.
    """
    from arena.desktop.backends import _win32_windows as mod

    listing = [(111, "Hidden", "Chrome_WidgetWin_1"), (222, "Shown", "Chrome_WidgetWin_1")]
    monkeypatch.setattr(mod, "_IS_WINDOWS", True)
    monkeypatch.setattr(mod, "user32", _fake_user32_listing(listing, hidden={111}))
    monkeypatch.setattr(mod, "_api", types.SimpleNamespace(EnumWindowsProc=lambda fn: fn))
    monkeypatch.setattr(mod, "_best_window_geometry", lambda hwnd, owner_pid: ({}, None, "test"))

    assert [w["id"] for w in mod.list_windows()] == ["222"]
    everything = mod.list_windows(visible_only=False)
    assert [w["id"] for w in everything] == ["111", "222"]
    assert [w["visible"] for w in everything] == [False, True]


def test_a_window_that_cannot_be_described_is_logged_not_swallowed(monkeypatch, caplog):
    """A dropped window must not be indistinguishable from no window.

    The callback cannot let the exception propagate -- it runs as a
    ctypes callback inside `EnumWindows`, and raising across that
    boundary aborts the walk and loses every window. But `except
    Exception: pass` made a window that failed to describe look exactly
    like a window that does not exist, which is the observability gap
    raised in review.
    """
    from arena.desktop.backends import _win32_windows as mod

    listing = [(111, "Fine", "Chrome_WidgetWin_1"), (222, "Broken", "Chrome_WidgetWin_1")]

    def _boom(hwnd, owner_pid):
        if hwnd == 222:
            raise OSError("window vanished mid-enumeration")
        return {}, None, "test"

    monkeypatch.setattr(mod, "_IS_WINDOWS", True)
    monkeypatch.setattr(mod, "user32", _fake_user32_listing(listing))
    monkeypatch.setattr(mod, "_api", types.SimpleNamespace(EnumWindowsProc=lambda fn: fn))
    monkeypatch.setattr(mod, "_best_window_geometry", _boom)

    with caplog.at_level("DEBUG", logger=mod.__name__):
        windows = mod.list_windows()

    assert [w["id"] for w in windows] == ["111"]
    assert any("222" in record.getMessage() for record in caplog.records), (
        "the dropped window left no trace in the log"
    )


def test_an_unexpected_failure_is_louder_than_a_vanished_window(monkeypatch, caplog):
    """A bug in this module must not read as "fewer windows today".

    `OSError` means a window closed mid-enumeration -- normal, logged
    at debug. A `TypeError` or `KeyError` means this code is wrong, and
    at debug it would be invisible in production where the level is
    usually higher. Raised in review, and the distinction is the point:
    the broad handler exists for the ctypes boundary, not to equate the
    two.
    """
    from arena.desktop.backends import _win32_windows as mod

    listing = [(111, "Fine", "Chrome_WidgetWin_1"), (222, "Broken", "Chrome_WidgetWin_1")]

    def _bug(hwnd, owner_pid):
        if hwnd == 222:
            raise TypeError("this is a programmer error, not a closed window")
        return {}, None, "test"

    monkeypatch.setattr(mod, "_IS_WINDOWS", True)
    monkeypatch.setattr(mod, "user32", _fake_user32_listing(listing))
    monkeypatch.setattr(mod, "_api", types.SimpleNamespace(EnumWindowsProc=lambda fn: fn))
    monkeypatch.setattr(mod, "_best_window_geometry", _bug)

    with caplog.at_level("WARNING", logger=mod.__name__):
        windows = mod.list_windows()

    assert [w["id"] for w in windows] == ["111"]
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    assert warnings, "a programmer error was logged at debug and would vanish in production"
    assert "222" in warnings[0].getMessage()


def test_a_broken_enumeration_is_not_reported_as_an_empty_desktop(monkeypatch):
    """`EnumWindows` returning zero must raise, not return a short list.

    The callback returns True on every path, so a zero return is the
    walk itself failing. Handing back whatever was collected says "this
    is the desktop" when the truthful answer is "the walk broke", and
    `window_catalog` turns the exception into `ok: False` with the
    message -- the difference between a caller that knows it has
    nothing and one that believes an empty desktop.
    """
    import types

    from arena.desktop.backends import _win32_windows as mod

    class _FailingEnum:
        def GetForegroundWindow(self):
            return 0

        def EnumWindows(self, cb, _lparam):
            cb(111, 0)
            return 0

        def IsWindowVisible(self, hwnd):
            return 1

        def GetWindowTextLengthW(self, hwnd):
            return 4

    monkeypatch.setattr(mod, "_IS_WINDOWS", True)
    monkeypatch.setattr(mod, "user32", _FailingEnum())
    monkeypatch.setattr(
        mod, "_api", types.SimpleNamespace(
            EnumWindowsProc=lambda fn: fn,
            kernel32=types.SimpleNamespace(GetLastError=lambda: 1400),
        )
    )
    monkeypatch.setattr(
        mod, "_describe_window",
        lambda hwnd, *, foreground, visible_only: {"id": str(hwnd), "active": False},
    )

    with pytest.raises(OSError) as caught:
        mod.list_windows_with_foreground(visible_only=False)

    assert caught.value.errno == 1400


def test_a_child_with_no_owning_process_is_left_out(monkeypatch):
    """A failed `GetWindowThreadProcessId` leaves pid at 0 -- the System
    Idle Process -- so an entry built from it does not look broken, it
    looks wrong. Raised in review: partial data that reads as valid is
    worse than a missing entry, because nothing downstream can tell.
    """
    import types

    from arena.desktop.backends import _win32_windows as mod

    class _NoPid:
        def EnumChildWindows(self, hwnd, cb, _lparam):
            cb(777, 0)
            return 1

        def IsWindowVisible(self, hwnd):
            return 1

        def GetWindowThreadProcessId(self, hwnd, _ref):
            return 0

        def IsIconic(self, hwnd):
            return 0

    monkeypatch.setattr(mod, "user32", _NoPid())
    monkeypatch.setattr(mod, "_api", types.SimpleNamespace(EnumWindowsProc=lambda fn: fn))
    monkeypatch.setattr(mod, "_window_text", lambda hwnd: ("t", "c"))
    monkeypatch.setattr(
        mod, "_window_rect_geometry",
        lambda hwnd: ({"x": 0, "y": 0, "width": 1, "height": 1}, "test"),
    )

    assert mod._child_window_candidates(1, owner_pid=None) == []


def test_a_zero_sized_window_is_still_a_real_measurement(monkeypatch):
    """An empty rect that the API *did* return is a fact, not a failure.

    The distinction the `unavailable` source exists to make: a
    collapsed window legitimately measures zero, and calling that
    "unavailable" would lose the difference between "the window has no
    size" and "we could not ask".
    """
    from arena.desktop.backends import _win32_windows as mod

    class _ZeroRect:
        def GetWindowRect(self, hwnd, ref):
            ref._obj.left = ref._obj.top = ref._obj.right = ref._obj.bottom = 0
            return 1

        def GetClientRect(self, hwnd, _ref):
            return 0

        def ClientToScreen(self, hwnd, _ref):
            return 0

    monkeypatch.setattr(mod, "user32", _ZeroRect())
    monkeypatch.setattr(mod, "dwmapi", None)

    geometry, source = mod._window_rect_geometry(4242)

    assert source == "get_window_rect"
    assert geometry == {"x": 0, "y": 0, "width": 0, "height": 0}


def test_a_failed_window_measurement_is_not_reported_as_a_measurement(monkeypatch):
    """`GetWindowRect` returning zero leaves the struct untouched.

    Reporting those defaults as geometry labelled `get_window_rect`
    claims an authority the call never gave, and downstream treats the
    source as authoritative. Raised in review.
    """
    from arena.desktop.backends import _win32_windows as mod

    class _FailingRect:
        def GetWindowRect(self, hwnd, _ref):
            return 0

        def GetClientRect(self, hwnd, _ref):
            return 0

        def ClientToScreen(self, hwnd, _ref):
            return 0

    monkeypatch.setattr(mod, "user32", _FailingRect())
    monkeypatch.setattr(mod, "dwmapi", None)

    geometry, source = mod._window_rect_geometry(4242)

    assert source == "unavailable"
    assert geometry == {"x": 0, "y": 0, "width": 0, "height": 0}


def test_a_null_foreground_is_reported_as_zero(monkeypatch):
    """`GetForegroundWindow` returns NULL when nothing has the focus.

    Its restype is `wt.HWND` (`c_void_p`), and ctypes hands back `None`
    rather than 0, so `int(fg)` raised `TypeError` straight out of
    `list_windows` -- on a locked screen, which is precisely the
    desktop state this issue is about. Raised in review.
    """
    from arena.desktop.backends import _win32_windows as mod

    class _NoForeground:
        def GetForegroundWindow(self):
            return None

        def EnumWindows(self, cb, _lparam):
            cb(111, 0)
            return True

        def IsWindowVisible(self, hwnd):
            return 1

        def GetWindowTextLengthW(self, hwnd):
            return 5

        def GetWindowTextW(self, hwnd, buf, _n):
            buf.value = "w111"
            return 4

        def GetClassNameW(self, hwnd, buf, _n):
            buf.value = "TestClass"
            return 9

        def GetWindowThreadProcessId(self, hwnd, pid_ref):
            pid_ref._obj.value = 4242
            return 1

        def IsIconic(self, hwnd):
            return 0

    monkeypatch.setattr(mod, "_IS_WINDOWS", True)
    monkeypatch.setattr(mod, "user32", _NoForeground())
    monkeypatch.setattr(mod, "_api", types.SimpleNamespace(EnumWindowsProc=lambda fn: fn))
    monkeypatch.setattr(mod, "_best_window_geometry", lambda hwnd, owner_pid: ({}, None, "test"))

    windows, foreground = mod.list_windows_with_foreground(visible_only=False)

    assert foreground == 0
    assert [w["id"] for w in windows if w["active"]] == []


def test_the_foreground_is_not_kept_on_the_module(monkeypatch):
    """A module-global would be shared between concurrent enumerations.

    These backend calls run under `run_in_executor`, so a second worker
    enumerating windows could overwrite a stashed snapshot between a
    caller's own call and its read -- raised in review on the previous
    revision, which did exactly that. The value is returned instead,
    and this keeps it that way.
    """
    from arena.desktop.backends import _win32_windows as enumeration, windows as mod

    stateful = [
        name
        for module in (mod, enumeration)
        for name in dir(module)
        if "LAST_FOREGROUND" in name.upper()
    ]
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
