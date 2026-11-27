"""The Windows side of input sequences: the SendInput driver, and `desktop.mouse` by a delta (#616, #617)."""
# The driver is given a stand-in for user32 that records what it was sent, so
# these run on any platform and move nothing.

from __future__ import annotations

import asyncio

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from arena.desktop.backends import windows_input
from arena.desktop.input import build_mouse_command
from arena.desktop.input_handlers import make_desktop_input_handlers
from arena.mcp.tool_registry import MCP_TOOLS
from tests._input_sequence_support import FakeUser32, handler_ctx


@pytest.fixture(name="user32")
def _user32() -> FakeUser32:
    return FakeUser32()


def test_a_key_is_sent_with_its_scan_code(user32):
    """A virtual key alone is not a key to a program that reads scan codes."""
    driver = windows_input.WindowsInputDriver(user32)
    driver.key_down("w")
    driver.key_up("w")
    down, up = (event.u.ki for event in user32.sent)
    assert user32.sent[0].type == windows_input.INPUT_KEYBOARD
    assert (down.wVk, down.wScan, down.dwFlags) == (0x57, 0x157, 0)
    assert (up.wVk, up.wScan, up.dwFlags) == (0x57, 0x157, windows_input.KEYEVENTF_KEYUP)


def test_an_arrow_key_carries_the_extended_bit(user32):
    """Without it the scan code is the numeric pad's 4, not the left arrow."""
    windows_input.WindowsInputDriver(user32).key_down("left")
    assert user32.sent[0].u.ki.dwFlags == windows_input.KEYEVENTF_EXTENDEDKEY


def test_relative_motion_is_a_move_event_and_not_a_cursor_jump(user32):
    windows_input.WindowsInputDriver(user32).move_rel(-8000, 12)
    event = user32.sent[0]
    assert event.type == windows_input.INPUT_MOUSE
    assert (event.u.mi.dx, event.u.mi.dy, event.u.mi.dwFlags) == (-8000, 12, windows_input.MOUSEEVENTF_MOVE)
    assert user32.cursor is None


def test_absolute_motion_sets_the_cursor(user32):
    windows_input.WindowsInputDriver(user32).move_to(1208, 976)
    assert user32.cursor == (1208, 976)
    assert user32.sent == []


def test_the_wheel_takes_notches_in_either_direction(user32):
    driver = windows_input.WindowsInputDriver(user32)
    driver.scroll(1)
    driver.scroll(-2)
    up, down = (event.u.mi for event in user32.sent)
    assert (up.dwFlags, up.mouseData) == (windows_input.MOUSEEVENTF_WHEEL, 120)
    assert down.mouseData == (-240) & 0xFFFFFFFF


@pytest.mark.parametrize(("button", "down", "up"), [
    ("left", 0x0002, 0x0004), ("right", 0x0008, 0x0010), ("middle", 0x0020, 0x0040)])
def test_each_button_has_its_own_pair_of_events(user32, button, down, up):
    driver = windows_input.WindowsInputDriver(user32)
    driver.button_down(button)
    driver.button_up(button)
    assert [event.u.mi.dwFlags for event in user32.sent] == [down, up]


def test_an_event_the_system_drops_is_an_error_and_not_a_silent_success(user32):
    user32.deliver = 0
    driver = windows_input.WindowsInputDriver(user32)
    with pytest.raises(OSError, match="delivered 0 of 1"):
        driver.key_down("w")


def test_a_cursor_the_system_will_not_move_is_an_error(user32):
    """A refused SetCursorPos answers zero; it does not raise."""
    user32.cursor_can_be_set = 0
    driver = windows_input.WindowsInputDriver(user32)
    with pytest.raises(OSError, match="SetCursorPos failed"):
        driver.move_to(10, 20)
    assert user32.cursor is None


def test_the_driver_reads_the_foreground_title_and_knows_its_keys(user32):
    driver = windows_input.WindowsInputDriver(user32)
    assert driver.foreground_title() == "Abyssal Ascent - Minecraft"
    assert driver.knows_key("f3")
    assert driver.knows_key("7")
    assert not driver.knows_key("hyper")


# ---------------------------------------------------------------------
# 6. desktop.mouse and `absolute: false` (#617)
# ---------------------------------------------------------------------
def test_xdotool_moves_by_a_delta_when_asked_to():
    """It used to send `mousemove -5 7`: a jump to a corner, reported as a relative move."""
    command, tool, error = build_mouse_command(env={"has_xdotool": True}, x=-5, y=7, absolute=False)
    assert error is None
    assert tool == "xdotool"
    assert command.endswith("xdotool mousemove_relative -- -5 7")


def test_xdotool_still_moves_to_a_point_by_default():
    command, _, _ = build_mouse_command(env={"has_xdotool": True}, x=50, y=60)
    assert command.endswith("xdotool mousemove 50 60")


def _mouse_route(body: dict):
    """POST /v1/desktop/mouse on a desktop that reports the native Windows backend."""
    ctx, _ = handler_ctx(env={"has_win32_input": True})
    mouse = make_desktop_input_handlers(ctx)[3]

    async def go():
        app = web.Application()
        app.router.add_post("/v1/desktop/mouse", mouse)
        async with TestClient(TestServer(app)) as client:
            response = await client.post("/v1/desktop/mouse", json=body)
            return response.status, await response.json()

    return asyncio.run(go())


def test_the_windows_route_moves_by_a_delta_when_asked_to(user32, monkeypatch):
    """It used to call SetCursorPos with the delta and answer `"absolute": false`."""
    monkeypatch.setattr(windows_input, "system_driver", lambda: windows_input.WindowsInputDriver(user32))
    user32.cursor = (1337, 511)
    status, body = _mouse_route({"x": -60, "y": 35, "absolute": False})
    assert status == 200
    assert body["absolute"] is False
    assert user32.cursor == (1277, 546)


def test_a_relative_move_of_the_cursor_is_in_pixels_not_in_device_motion(user32, monkeypatch):
    """Found on a real desktop: with the pointer speed at 1 of 20, 640 counts of motion moved the cursor 20 px."""
    monkeypatch.setattr(windows_input, "system_driver", lambda: windows_input.WindowsInputDriver(user32))
    user32.cursor = (0, 0)
    _mouse_route({"x": 640, "y": 320, "absolute": False})
    assert user32.sent == [], "SendInput motion is scaled by the pointer speed before it reaches the cursor"
    assert user32.cursor == (640, 320)


def test_a_cursor_that_cannot_be_read_is_a_500_and_nothing_moves(user32, monkeypatch):
    monkeypatch.setattr(windows_input, "system_driver", lambda: windows_input.WindowsInputDriver(user32))
    user32.cursor = (10, 10)
    user32.cursor_is_readable = 0
    status, body = _mouse_route({"x": 5, "y": 5, "absolute": False})
    assert status == 500
    assert "GetCursorPos failed" in body["error"]
    assert user32.cursor == (10, 10)


def test_a_windows_move_the_system_refuses_is_a_500_with_the_reason(monkeypatch):
    def refuse(x, y, absolute=True):
        raise OSError("SendInput delivered 0 of 1 events")

    monkeypatch.setattr(windows_input, "mouse_move", refuse)
    status, body = _mouse_route({"x": 1, "y": 1, "absolute": False})
    assert status == 500
    assert body == {"ok": False, "error": "Windows mouse move failed: SendInput delivered 0 of 1 events"}


def test_the_description_no_longer_promises_more_than_the_tool_does():
    tool = next(tool for tool in MCP_TOOLS if tool["name"] == "desktop.mouse")
    assert "by (x, y) pixels when `absolute` is false" in tool["description"]
    assert "raw mouse motion" in tool["description"]
    assert "desktop.sequence" in tool["description"]
