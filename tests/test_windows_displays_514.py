"""#514: the displays endpoint answers on Windows, one entry per monitor."""
from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from arena.desktop import displays
from arena.desktop.backends import windows_displays

LAPTOP = {"device": "\\\\.\\DISPLAY1", "rect": (0, 0, 2560, 1440), "work": (0, 0, 2560, 1380), "primary": True, "dpi": 144}
SIDE = {"device": "\\\\.\\DISPLAY2", "rect": (-1920, 0, 0, 1080), "work": (-1920, 0, 0, 1040), "primary": False, "dpi": 96}


def _fill(rect, edges):
    rect.left, rect.top, rect.right, rect.bottom = edges


def _user32(monitors, foreground=1):
    """Stand in for user32: monitor handles are 1, 2, ... in the order given."""
    def enumerate_monitors(_dc, _clip, callback, _data):
        return all(callback(handle, None, None, 0) for handle in range(1, len(monitors) + 1))

    def monitor_info(handle, reference):
        info, monitor = reference.contents, monitors[handle - 1]
        _fill(info.rcMonitor, monitor["rect"])
        _fill(info.rcWork, monitor["work"])
        info.dwFlags, info.szDevice = int(monitor["primary"]), monitor["device"]
        return 1

    return SimpleNamespace(
        EnumDisplayMonitors=enumerate_monitors,
        GetMonitorInfoW=monitor_info,
        GetForegroundWindow=lambda: 77,
        MonitorFromWindow=lambda window, _flags: foreground if window == 77 else 0,
    )


def _shcore(monitors):
    def dpi_for_monitor(handle, _kind, horizontal, vertical):
        horizontal.contents.value = vertical.contents.value = monitors[handle - 1]["dpi"]
        return 0

    return SimpleNamespace(GetDpiForMonitor=dpi_for_monitor)


def test_one_scaled_display_is_described_in_physical_pixels():
    """The machine the bug was found on: 2560x1440 at 150 %."""
    found = windows_displays.enumerate_displays(_user32([LAPTOP]), _shcore([LAPTOP]))
    assert found == [{
        "index": 1,
        "name": "DISPLAY1",
        "id": "\\\\.\\DISPLAY1",
        "connected": True,
        "enabled": True,
        "primary": True,
        "active": True,
        "geometry": {"x": 0, "y": 0, "width": 2560, "height": 1440},
        "work_area": {"x": 0, "y": 0, "width": 2560, "height": 1380},
        "dpi": 144,
        "scale": 1.5,
        "backend": "win32",
    }]


def test_a_display_left_of_the_primary_keeps_its_negative_origin():
    """Coordinates are those of the virtual screen, the ones a click takes."""
    found = windows_displays.enumerate_displays(_user32([LAPTOP, SIDE], foreground=2), _shcore([LAPTOP, SIDE]))
    side = found[1]
    assert side["geometry"] == {"x": -1920, "y": 0, "width": 1920, "height": 1080}
    assert [(d["name"], d["primary"], d["active"], d["scale"]) for d in found] == [
        ("DISPLAY1", True, False, 1.5), ("DISPLAY2", False, True, 1.0)]


@pytest.mark.parametrize("shcore", [None, SimpleNamespace(GetDpiForMonitor=lambda *_: -1)])
def test_an_unknown_scale_is_reported_as_unknown(shcore):
    """Before Windows 8.1, or when the call is refused: null, not a guessed 100 %."""
    found = windows_displays.enumerate_displays(_user32([LAPTOP]), shcore)
    assert (found[0]["dpi"], found[0]["scale"]) == (None, None)


def test_a_failed_enumeration_is_an_error_not_an_empty_list():
    """Zero displays was the bug; a failure must not look like it."""
    user = _user32([LAPTOP])
    user.EnumDisplayMonitors = lambda *_: 0
    with pytest.raises(OSError, match="EnumDisplayMonitors"):
        windows_displays.enumerate_displays(user, None)


async def _no_tools(cmd, timeout=10):
    raise AssertionError(f"Linux tool asked on Windows: {cmd}")


def test_the_windows_environment_gets_the_native_answer(monkeypatch):
    """No kscreen-doctor, no xrandr: the answer comes from user32, and names the active display."""
    monkeypatch.setattr(windows_displays, "list_displays",
                        lambda: windows_displays.enumerate_displays(_user32([LAPTOP, SIDE]), _shcore([LAPTOP, SIDE])))
    result = asyncio.run(displays.get_displays(desktop_exec=_no_tools, env={"has_win32_windows": True}))
    assert (result["ok"], result["backend"], result["count"], result["active_output"]) == (True, "win32", 2, "DISPLAY1")
    assert displays.match_display(result["displays"], "display2")["geometry"]["x"] == -1920


def test_a_native_failure_is_reported_as_one(monkeypatch):
    """The handler turns ok=False into a 500; "no displays" would be a wrong answer."""
    def fail():
        raise OSError("EnumDisplayMonitors failed")

    monkeypatch.setattr(windows_displays, "list_displays", fail)
    result = asyncio.run(displays.get_displays(desktop_exec=_no_tools, env={"has_win32_windows": True}))
    assert (result["ok"], result["count"], result["attempts"][0]["ok"]) == (False, 0, False)
    assert "EnumDisplayMonitors" in result["error"]


XRANDR = "DP-1 connected primary 2560x1440+0+0 (normal left inverted right)\nHDMI-1 connected 1920x1080+2560+0 (normal left)\n"


def _linux_tools(answers):
    """Stand in for the shell: `answers` maps a tool's name to what it prints."""
    async def run(cmd, timeout=10):
        stdout = next((text for tool, text in answers.items() if tool in cmd), None)
        return {"ok": stdout is not None, "stdout": stdout or "", "stderr": ""}

    return run


@pytest.mark.parametrize("env", [None, {}, {"has_win32_windows": False}])
def test_elsewhere_xrandr_answers_when_kscreen_doctor_does_not(env):
    """The Linux path is the one it was: kscreen-doctor first, then xrandr."""
    result = asyncio.run(displays.get_displays(desktop_exec=_linux_tools({"xrandr": XRANDR, "activeOutputName": "HDMI-1\n"}), env=env))
    assert (result["backend"], result["count"], result["active_output"]) == ("xrandr", 2, "HDMI-1")
    assert [(d["name"], d["primary"], d["active"]) for d in result["displays"]] == [("DP-1", True, False), ("HDMI-1", False, True)]
    assert result["attempts"] == [{"tool": "kscreen_doctor", "ok": False}, {"tool": "xrandr", "ok": True}]


@pytest.mark.parametrize("answers", [{}, {"kscreen-doctor": "", "xrandr": "no outputs here\n"}])
def test_elsewhere_no_tool_means_no_displays(answers):
    """Neither tool installed, or neither printing an output: an empty list, as before."""
    result = asyncio.run(displays.get_displays(desktop_exec=_linux_tools(answers)))
    assert (result["ok"], result["backend"], result["count"], result["displays"], result["active_output"]) == (True, "none", 0, [], None)
    assert [attempt["tool"] for attempt in result["attempts"]] == ["kscreen_doctor", "xrandr"]


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows display API")
def test_live_the_displays_tile_the_virtual_screen():
    """On a real desktop: at least one display, one primary, and none outside the virtual screen."""
    from arena.desktop.backends import windows

    found = windows_displays.list_displays()
    left, top, width, height = windows.virtual_screen_rect()
    assert [d["primary"] for d in found].count(True) == 1
    for display in found:
        geometry = display["geometry"]
        assert left <= geometry["x"] < geometry["x"] + geometry["width"] <= left + width
        assert top <= geometry["y"] < geometry["y"] + geometry["height"] <= top + height


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows display API")
def test_live_the_endpoint_answers_for_this_machine():
    """The whole path the handler takes, with the environment as it is detected here."""
    from arena.desktop.env import _detect_desktop_env

    result = asyncio.run(displays.get_displays(desktop_exec=_no_tools, env=_detect_desktop_env()))
    assert (result["ok"], result["backend"]) == (True, "win32")
    assert result["count"] >= 1
    assert result["active_output"] in [d["name"] for d in result["displays"]]


@pytest.mark.skipif(sys.platform == "win32", reason="the refusal is for other platforms")
def test_other_platforms_are_refused():
    with pytest.raises(NotImplementedError):
        windows_displays.list_displays()
