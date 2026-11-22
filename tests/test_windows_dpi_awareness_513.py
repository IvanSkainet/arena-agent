"""#513: the Windows desktop API works in one coordinate space, physical pixels."""

# Seen on a 2560x1440 display at 150 % scaling: the bridge process had never
# declared DPI awareness, so GetSystemMetrics answered 1707x960 and the default
# screenshot copied only that much of the screen, window geometry came back in
# physical pixels through DWM, and clicks were placed in logical ones.

from __future__ import annotations

import struct
import sys
from types import SimpleNamespace

import pytest

from arena.desktop.backends import _win32_api
from arena.input_helper import helper_server

ALREADY_DECIDED = -0x7FF8FFFB  # the HRESULT shcore answers once the awareness is set


# Leaving `context` out removes the Windows 10 request, and `awareness=None`
# removes the query, as on a Windows that predates them.
def _user32(calls, **answers):
    """Stand in for user32: `context` and `legacy` answer the requests, `awareness` the query."""
    user = SimpleNamespace(SetProcessDPIAware=lambda: calls.append(("legacy",)) or answers.get("legacy", 1))
    if "context" in answers:
        user.SetProcessDpiAwarenessContext = lambda handle: calls.append(("context", handle.value)) or answers["context"]
    if answers.get("awareness", 2) is not None:
        user.GetThreadDpiAwarenessContext = lambda: 0x12
        user.GetAwarenessFromDpiAwarenessContext = lambda handle: answers.get("awareness", 2) if handle.value == 0x12 else -1
    return user


def _shcore(calls, result):
    return SimpleNamespace(SetProcessDpiAwareness=lambda level: calls.append(("shcore", level)) or result)


DECLARATIONS = pytest.mark.parametrize(
    "declare", [_win32_api.declare_dpi_awareness, helper_server.declare_dpi_awareness], ids=["bridge", "helper"])


@DECLARATIONS
def test_the_newest_request_is_enough_when_windows_accepts_it(declare):
    """Per-monitor awareness is asked for first and nothing older is tried after it."""
    calls = []
    declare(_user32(calls, context=1), _shcore(calls, 0))
    # c_void_p(-4) reads back unsigned; the handle is DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2.
    assert [name for name, *_ in calls] == ["context"]
    assert calls[0][1] in (-4, 2**64 - 4, 2**32 - 4)


@DECLARATIONS
def test_a_refusal_falls_through_to_the_older_requests(declare):
    """Windows refusing one generation is not an error; the next one is tried."""
    calls = []
    declare(_user32(calls, context=0), _shcore(calls, ALREADY_DECIDED))
    assert [name for name, *_ in calls] == ["context", "shcore", "legacy"]
    assert calls[1] == ("shcore", 2)


@DECLARATIONS
def test_an_old_windows_without_the_newer_calls_still_gets_asked(declare):
    """Missing entry points and a missing shcore.dll are skipped, not raised."""
    calls = []
    declare(_user32(calls, awareness=None), None)
    assert calls == [("legacy",)]


@DECLARATIONS
def test_an_accepted_middle_request_stops_the_chain(declare):
    """Windows 8.1: no context call, shcore accepts, the legacy call is not made."""
    calls = []
    declare(_user32(calls), _shcore(calls, 0))
    assert calls == [("shcore", 2)]


@DECLARATIONS
@pytest.mark.parametrize("awareness", [2, 1, 0, None])
def test_the_answer_is_what_windows_reports_afterwards(declare, awareness):
    """Not the request that was made: every request here is refused."""
    assert declare(_user32([], context=0, legacy=0, awareness=awareness), None) == awareness


@pytest.mark.parametrize(("awareness", "warned"), [(0, True), (1, False), (2, False), (None, False)])
def test_an_unaware_bridge_says_so_in_the_log(caplog, awareness, warned):
    """The declaration cannot be forced; a pinned executable is reported, not hidden."""
    with caplog.at_level("WARNING", logger=_win32_api.__name__):
        _win32_api.declare_dpi_awareness(_user32([], context=0, legacy=0, awareness=awareness), None)
    assert ("desktop coordinates will not match screenshots" in caplog.text) is warned


def test_the_helper_reports_its_awareness_in_health(monkeypatch):
    """A helper older than this change has no such field, which is how to tell them apart."""
    sent = []
    handler = object.__new__(helper_server.InputHandler)
    handler.path = "/health"
    monkeypatch.setattr(helper_server, "user32", _user32([], awareness=2))
    monkeypatch.setattr(helper_server.InputHandler, "_check_auth", lambda self: True)
    monkeypatch.setattr(helper_server.InputHandler, "_json_response", lambda self, payload, status=200: sent.append(payload))
    handler.do_GET()
    assert sent[0]["dpi_awareness"] == 2


def test_the_helper_declares_before_it_serves(monkeypatch):
    """The helper is its own process, so it makes the request itself at startup."""
    events = []

    class Server:
        def __init__(self, address, handler):
            events.append("listen")

        def serve_forever(self):
            raise KeyboardInterrupt

        def server_close(self):
            events.append("close")

        def shutdown(self):
            events.append("close")

    # Stand-ins for the two modules, so nothing process-wide is touched.
    monkeypatch.setattr(sys, "argv", ["helper_server.py", "--token", "t" * 32, "--port", "0"])
    monkeypatch.setattr(helper_server, "sys", SimpleNamespace(platform="win32", stderr=sys.stderr))
    monkeypatch.setattr(helper_server, "_shcore", lambda: None)
    monkeypatch.setattr(helper_server, "user32", SimpleNamespace())
    monkeypatch.setattr(helper_server, "declare_dpi_awareness", lambda user, shcore: events.append("declare") or 2)
    monkeypatch.setattr(helper_server, "HTTPServer", Server)
    helper_server.main()
    assert events[:2] == ["declare", "listen"]


def test_off_windows_nothing_is_declared():
    """Importing the backend elsewhere leaves the constant unset."""
    if sys.platform != "win32":
        assert _win32_api.DPI_AWARENESS is None


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows DPI API")
def test_live_the_backend_process_is_per_monitor_aware():
    """After import, this process is told physical pixels on every display."""
    if _win32_api.DPI_AWARENESS is None:
        pytest.skip("this Windows cannot report the awareness in effect")
    assert _win32_api.DPI_AWARENESS == _win32_api.DPI_PER_MONITOR_AWARE


def _image_size(data):
    """Read width and height from a PNG or BMP header."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    width, height = struct.unpack("<ii", data[18:26])
    return width, abs(height)


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows capture")
def test_live_the_default_screenshot_covers_the_whole_desktop():
    """The default capture is as large as the desktop, and the desktop is not scaled down."""
    # A hosted runner has no scaling, so there the second half holds either
    # way; on a scaled display it is the check that failed before the
    # declaration.
    import ctypes
    import ctypes.wintypes as wt

    from arena.desktop.backends import windows

    _x, _y, width, height = windows.virtual_screen_rect()
    assert _image_size(windows.capture_screenshot()) == (width, height)
    gdi32 = ctypes.windll.gdi32
    gdi32.GetDeviceCaps.argtypes = [wt.HDC, ctypes.c_int]
    dc = _win32_api.user32.GetDC(None)
    try:
        # DESKTOPHORZRES and DESKTOPVERTRES: the primary display, unscaled whatever the process declared.
        physical = (gdi32.GetDeviceCaps(dc, 118), gdi32.GetDeviceCaps(dc, 117))
    finally:
        _win32_api.user32.ReleaseDC(None, dc)
    assert width >= physical[0]
    assert height >= physical[1]
