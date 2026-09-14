"""Window enumeration for the Windows desktop backend (#351).

Split out of `test_desktop_windows_backend.py` along the same line the
production code was split: enumeration lives in
`arena/desktop/backends/_win32_windows.py`, so its tests live here.
CodeScene flagged the combined file for low cohesion and was right --
it had grown to hold the backend's router, its encoders, its key map
and the whole of this, which is a different subject with a different
reason to change.

The subject: `list_windows` reports which window holds the focus, and
under #351 it could report none while a window plainly had it. Several
of these tests carry a note about an earlier revision of themselves
that passed for the wrong reason.
"""
from __future__ import annotations

import sys
import types

import pytest

from arena.desktop.backends import windows as win_backend

_WIN_ONLY = pytest.mark.skipif(sys.platform != "win32", reason="requires native Windows")


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
    # Filtered to DEBUG deliberately. Asserting only that 222 appears
    # *somewhere* in the log would also pass if a vanished window were
    # reported at WARNING -- the level this module reserves for its own
    # bugs -- so the quiet-vs-loud split would be pinned from one side
    # only. Raised in review; the sibling test names WARNING, so this
    # one names DEBUG.
    quiet = [r for r in caplog.records if r.levelname == "DEBUG" and "222" in r.getMessage()]
    assert quiet, (
        "the dropped window left no DEBUG trace: "
        f"{[(r.levelname, r.getMessage()) for r in caplog.records]}"
    )
    assert not [r for r in caplog.records if r.levelno > 20], (
        "a window that merely closed was reported as a fault"
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
