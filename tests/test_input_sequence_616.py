"""Timed input sequences: held keys, relative motion, one call (#616, #617).

`desktop.key` presses and releases in one call and `desktop.mouse` only
teleports the cursor, so an agent could not hold a key, turn a camera or time
two actions against each other. `POST /v1/desktop/sequence` runs a list of
steps on the host. These tests pin the properties that make that safe to
hand to an agent:

* a bad step is refused before anything is pressed;
* whatever was pressed is released, however the sequence ends;
* the sequence names its window and stops when another one is in front;
* a paused control lease stops it in the middle.

Nothing here sends real input: the driver is a recorder, and the Windows
driver is given a stand-in for user32.
"""
from __future__ import annotations

import asyncio
import ctypes
import io
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from arena.desktop import input_sequence_handler
from arena.desktop.backends import windows_input
from arena.desktop.input import build_mouse_command
from arena.desktop.input_sequence import (
    MAX_HOLD_MS,
    MAX_STEPS,
    MAX_TOTAL_MS,
    SequenceError,
    plan_sequence,
    planned_duration_ms,
    run_sequence,
)
from arena.extension_bridge.policy import classify_tool_risk
from arena.mcp import tool_desktop_sequence
from arena.mcp.tool_registry import MCP_TOOLS
from arena.route_registry.registry import ROUTES
from tests._live_bridge import auth_header, json_payload, running_client

TITLE = "Game"


class Recorder:
    """An input driver that writes down what it was asked to do."""

    def __init__(self, title: str = "My Game Window") -> None:
        self.events: list[tuple] = []
        self.title = title
        self.fail_on: str | None = None

    def _note(self, *event) -> None:
        if self.fail_on == event[0]:
            raise OSError("SendInput delivered 0 of 1 events")
        self.events.append(event)

    def knows_key(self, name: str) -> bool:
        return name in {"w", "space", "shift", "f3", "esc"}

    def key_down(self, name): self._note("key_down", name)
    def key_up(self, name): self._note("key_up", name)
    def button_down(self, name): self._note("button_down", name)
    def button_up(self, name): self._note("button_up", name)
    def move_rel(self, dx, dy): self._note("move_rel", dx, dy)
    def move_to(self, x, y): self._note("move_to", x, y)
    def scroll(self, clicks): self._note("scroll", clicks)
    def foreground_title(self) -> str: return self.title


class Clock:
    """Virtual time: sleeping advances it, so no test waits for real."""

    def __init__(self) -> None:
        self.now = 0.0
        self.on_sleep = None

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        if self.on_sleep:
            self.on_sleep(self.now)


def _run(steps, driver=None, *, clock=None, should_stop=None, title=TITLE):
    driver = driver or Recorder()
    clock = clock or Clock()
    planned = plan_sequence(steps, driver)
    result = run_sequence(planned, driver, required_title=title, should_stop=should_stop,
                          sleep=clock.sleep, clock=clock.time)
    return result, driver, clock


# ---------------------------------------------------------------------
# 1. the plan: refused before anything is pressed
# ---------------------------------------------------------------------
@pytest.mark.parametrize(("steps", "fragment"), [
    (None, "non-empty list"),
    ([], "non-empty list"),
    ([{"do": "wait", "ms": 1}] * (MAX_STEPS + 1), "at most"),
    (["tap"], "must be an object"),
    ([{"do": "explode"}], "'do' must be one of"),
    ([{"do": "tap"}], "'key' must be a key name"),
    ([{"do": "tap", "key": "hyper"}], "unknown key 'hyper'"),
    ([{"do": "click", "button": "fourth"}], "'button' must be one of"),
    ([{"do": "wait"}], "'ms' must be an integer"),
    ([{"do": "wait", "ms": True}], "'ms' must be an integer"),
    ([{"do": "wait", "ms": -1}], "between 0 and"),
    ([{"do": "tap", "key": "w", "ms": MAX_HOLD_MS + 1}], "between 1 and"),
    ([{"do": "move", "dx": 1.5}], "'dx' must be an integer"),
    ([{"do": "move_to", "x": 1}], "'y' must be an integer"),
    ([{"do": "scroll", "clicks": 1000}], "between -100 and 100"),
])
def test_a_bad_step_is_refused_with_its_reason(steps, fragment):
    with pytest.raises(SequenceError, match=fragment):
        plan_sequence(steps, Recorder())


def test_the_refusal_names_the_step():
    with pytest.raises(SequenceError) as caught:
        plan_sequence([{"do": "wait", "ms": 1}, {"do": "tap", "key": "hyper"}], Recorder())
    assert caught.value.index == 1


def test_a_sequence_longer_than_the_limit_is_refused():
    steps = [{"do": "wait", "ms": MAX_TOTAL_MS // 2}] * 3
    with pytest.raises(SequenceError, match="the limit is"):
        plan_sequence(steps, Recorder())


def test_a_key_held_past_the_limit_is_refused():
    """Found by adding up the waits between the press and the release."""
    steps = [{"do": "key_down", "key": "w"}, {"do": "wait", "ms": 9_000},
             {"do": "wait", "ms": 9_000}, {"do": "key_up", "key": "w"}]
    with pytest.raises(SequenceError, match="key:w would stay down longer"):
        plan_sequence(steps, Recorder())


def test_a_button_never_released_counts_as_held_to_the_end():
    steps = [{"do": "mouse_down"}, {"do": "wait", "ms": MAX_HOLD_MS + 1}]
    with pytest.raises(SequenceError, match="button:left would stay down longer"):
        plan_sequence(steps, Recorder())


def test_a_hold_released_in_time_is_accepted_and_names_are_normalised():
    steps = [{"do": "key_down", "key": " W "}, {"do": "wait", "ms": MAX_HOLD_MS}, {"do": "key_up", "key": "w"}]
    planned = plan_sequence(steps, Recorder())
    assert planned[0] == {"do": "key_down", "key": "w"}
    assert planned_duration_ms(planned) == MAX_HOLD_MS


# ---------------------------------------------------------------------
# 2. the run
# ---------------------------------------------------------------------
def test_two_actions_are_timed_against_each_other():
    """The case from the issue: hold jump, 280 ms later right-click, let go."""
    result, driver, clock = _run([
        {"do": "key_down", "key": "space"}, {"do": "wait", "ms": 280},
        {"do": "click", "button": "right", "ms": 50}, {"do": "key_up", "key": "space"},
    ])
    assert driver.events == [
        ("key_down", "space"), ("button_down", "right"), ("button_up", "right"), ("key_up", "space")]
    assert result["ok"] is True
    assert result["steps_done"] == result["steps_total"] == 4
    assert result["elapsed_ms"] == 330 == round(clock.now * 1000)
    assert result["released_at_end"] == {"keys": [], "buttons": []}


def test_what_the_caller_forgot_to_release_is_released():
    result, driver, _ = _run([
        {"do": "key_down", "key": "shift"}, {"do": "key_down", "key": "w"}, {"do": "mouse_down"},
        {"do": "wait", "ms": 100},
    ])
    assert result["ok"] is True
    assert result["released_at_end"] == {"keys": ["w", "shift"], "buttons": ["left"]}
    assert driver.events[-3:] == [("button_up", "left"), ("key_up", "w"), ("key_up", "shift")]


def test_another_window_in_front_stops_the_sequence_before_it_starts():
    result, driver, _ = _run([{"do": "tap", "key": "w"}], Recorder(title="Terminal"))
    assert driver.events == []
    assert result["ok"] is False
    assert result["error"] == "input_guard_failed"
    assert result["active_title"] == "Terminal"
    assert result["steps_done"] == 0


def test_a_window_change_during_a_hold_releases_the_key():
    driver, clock = Recorder(), Clock()

    def lose_focus(now: float) -> None:
        if now >= 0.2:
            driver.title = "Save changes?"

    clock.on_sleep = lose_focus
    result, _, _ = _run([{"do": "key_down", "key": "w"}, {"do": "wait", "ms": 5_000},
                         {"do": "key_up", "key": "w"}, {"do": "tap", "key": "space"}], driver, clock=clock)
    assert driver.events == [("key_down", "w"), ("key_up", "w")]
    assert result["error"] == "input_guard_failed"
    assert result["steps_done"] == 1
    assert result["released_at_end"] == {"keys": ["w"], "buttons": []}
    assert result["elapsed_ms"] < 400


def test_the_title_match_ignores_case():
    result, _, _ = _run([{"do": "tap", "key": "w"}], Recorder(title="MY GAME"), title="my game")
    assert result["ok"] is True


def test_a_paused_lease_stops_the_sequence_in_the_bridge_s_own_words():
    clock = Clock()
    paused = {"ok": False, "error": "control_paused", "message": "Agent desktop control is paused by user",
              "status": "paused", "reason": "hands off"}
    result, driver, _ = _run(
        [{"do": "mouse_down"}, {"do": "wait", "ms": 3_000}, {"do": "mouse_up"}],
        clock=clock, should_stop=lambda: paused if clock.now >= 1.0 else None)
    assert driver.events == [("button_down", "left"), ("button_up", "left")]
    assert result["ok"] is False
    assert result["error"] == "control_paused"
    assert result["reason"] == "hands off"
    assert result["released_at_end"] == {"keys": [], "buttons": ["left"]}


def test_an_input_the_system_refuses_is_reported_and_the_rest_is_released():
    driver = Recorder()
    driver.fail_on = "move_rel"
    result, _, _ = _run([{"do": "key_down", "key": "w"}, {"do": "move", "dx": 10}], driver)
    assert result["ok"] is False
    assert result["error"] == "input_failed"
    assert "SendInput" in result["message"]
    assert driver.events == [("key_down", "w"), ("key_up", "w")]


def test_one_failed_release_does_not_strand_the_others():
    class StickyShift(Recorder):
        def key_up(self, name):
            if name == "shift":
                raise OSError("blocked")
            super().key_up(name)

    result, driver, _ = _run([{"do": "key_down", "key": "w"}, {"do": "key_down", "key": "shift"}], StickyShift())
    assert ("key_up", "w") in driver.events
    assert result["released_at_end"] == {"keys": ["w"], "buttons": []}
    # A key the system would not let go is still down for the user: the result says which.
    assert result["ok"] is False and result["error"] == "input_failed"
    assert result["release_failed"] == ["key:shift"]
    assert "key:shift" in result["message"]


def test_a_move_without_a_duration_is_one_event():
    _, driver, clock = _run([{"do": "move", "dx": -8000, "dy": 3}])
    assert driver.events == [("move_rel", -8000, 3)]
    assert clock.now == 0


def test_a_move_spread_over_time_adds_up_to_the_exact_delta():
    """A turn is only as good as its sum: lost counts are a camera that drifts."""
    _, driver, clock = _run([{"do": "move", "dx": 13_601, "dy": -77, "ms": 400}])
    moves = [event for event in driver.events if event[0] == "move_rel"]
    assert len(moves) > 10
    assert sum(event[1] for event in moves) == 13_601
    assert sum(event[2] for event in moves) == -77
    assert 0.3 <= clock.now <= 0.401


def test_absolute_moves_and_the_wheel_reach_the_driver():
    _, driver, _ = _run([{"do": "move_to", "x": 1208, "y": 976}, {"do": "scroll", "clicks": -2}])
    assert driver.events == [("move_to", 1208, 976), ("scroll", -2)]


# ---------------------------------------------------------------------
# 3. the Windows driver, against a stand-in for user32
# ---------------------------------------------------------------------
class FakeUser32:
    def __init__(self) -> None:
        self.sent: list[windows_input.INPUT] = []
        self.cursor: tuple[int, int] | None = None
        self.deliver = 1

    def SendInput(self, count, pointer, size):  # noqa: N802 -- the Win32 name
        assert count == 1
        assert size == ctypes.sizeof(windows_input.INPUT)
        self.sent.append(pointer._obj)
        return self.deliver

    def MapVirtualKeyW(self, vk, kind):  # noqa: N802
        assert kind == 0
        return 0x100 + vk

    def SetCursorPos(self, x, y):  # noqa: N802
        self.cursor = (x, y)

    def GetForegroundWindow(self):  # noqa: N802
        return 42

    def GetWindowTextW(self, hwnd, buffer, size):  # noqa: N802
        assert hwnd == 42
        buffer.value = "Abyssal Ascent - Minecraft"[: size - 1]


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
    with pytest.raises(OSError, match="delivered 0 of 1"):
        windows_input.WindowsInputDriver(user32).key_down("w")


def test_the_driver_reads_the_foreground_title_and_knows_its_keys(user32):
    driver = windows_input.WindowsInputDriver(user32)
    assert driver.foreground_title() == "Abyssal Ascent - Minecraft"
    assert driver.knows_key("f3") and driver.knows_key("7") and not driver.knows_key("hyper")


# ---------------------------------------------------------------------
# 4. the route
# ---------------------------------------------------------------------
def _handler_ctx(*, env=None, control=lambda: None):
    recorded: list[dict] = []
    ctx = SimpleNamespace(
        require_auth=lambda request: None,
        record_request=lambda **kwargs: recorded.append(kwargs),
        cors_json_response=lambda payload, status=200: web.json_response(payload, status=status),
        control_check=control,
        control_record_agent_action=lambda: recorded.append({"agent_action": True}),
        detect_desktop_env=lambda: env if env is not None else {"has_win32_input": True},
    )
    return ctx, recorded


def _post(ctx, body):
    async def go():
        app = web.Application()
        app.router.add_post("/v1/desktop/sequence", input_sequence_handler.make_desktop_sequence_handler(ctx))
        async with TestClient(TestServer(app)) as client:
            response = await client.post("/v1/desktop/sequence", json=body)
            return response.status, await response.json()

    return asyncio.run(go())


@pytest.fixture(name="driver")
def _driver(monkeypatch) -> Recorder:
    driver = Recorder()
    monkeypatch.setattr(input_sequence_handler, "sequence_driver", lambda env: driver)
    return driver


def test_the_route_runs_a_sequence_and_reports_it(driver):
    ctx, recorded = _handler_ctx()
    status, body = _post(ctx, {"require_active_title": "game", "steps": [
        {"do": "key_down", "key": "w"}, {"do": "wait", "ms": 30}, {"do": "key_up", "key": "w"}]})
    assert status == 200
    assert body["ok"] is True and body["steps_done"] == 3
    assert driver.events == [("key_down", "w"), ("key_up", "w")]
    assert {"agent_action": True} in recorded


@pytest.mark.parametrize("body", [
    {"steps": [{"do": "tap", "key": "w"}]},
    {"steps": [{"do": "tap", "key": "w"}], "require_active_title": "   "},
    {"steps": [{"do": "tap", "key": "w"}], "require_active_title": 7},
])
def test_a_sequence_that_does_not_name_its_window_is_refused(driver, body):
    ctx, _ = _handler_ctx()
    status, answer = _post(ctx, body)
    assert status == 400
    assert "require_active_title" in answer["error"]
    assert driver.events == []


def test_a_bad_step_is_a_400_that_names_the_step(driver):
    ctx, recorded = _handler_ctx()
    status, body = _post(ctx, {"require_active_title": "game", "steps": [
        {"do": "tap", "key": "w"}, {"do": "tap", "key": "hyper"}]})
    assert status == 400
    assert body == {"ok": False, "error": "step 1: unknown key 'hyper'", "step": 1}
    assert driver.events == []
    assert {"agent_action": True} not in recorded


def test_the_wrong_window_is_a_409(driver):
    driver.title = "Terminal"
    ctx, _ = _handler_ctx()
    status, body = _post(ctx, {"require_active_title": "game", "steps": [{"do": "tap", "key": "w"}]})
    assert status == 409
    assert body["error"] == "input_guard_failed" and body["active_title"] == "Terminal"
    assert driver.events == []


def test_a_lease_paused_mid_sequence_is_a_403_and_releases(driver):
    calls = {"n": 0}

    def control():
        calls["n"] += 1
        if calls["n"] > 2:
            return {"ok": False, "error": "control_paused", "status": "paused", "reason": None}
        return None

    ctx, _ = _handler_ctx(control=control)
    status, body = _post(ctx, {"require_active_title": "game", "steps": [
        {"do": "key_down", "key": "w"}, {"do": "wait", "ms": 200}, {"do": "key_up", "key": "w"}]})
    assert status == 403
    assert body["error"] == "control_paused"
    assert driver.events == [("key_down", "w"), ("key_up", "w")]


def test_a_desktop_without_a_driver_says_so_instead_of_pretending():
    ctx, _ = _handler_ctx(env={"has_win32_input": False, "has_xdotool": True})
    status, body = _post(ctx, {"require_active_title": "game", "steps": [{"do": "tap", "key": "w"}]})
    assert status == 501
    assert body["ok"] is False and "Windows" in body["error"]


def test_the_route_is_registered_and_guarded_on_a_running_bridge(tmp_path: Path):
    """Through the real application: auth first, then the window guard or the honest 501."""
    token = "sequence-616-token"

    async def go():
        async with running_client(tmp_path, token) as client:
            anonymous = await client.post("/v1/desktop/sequence", json={})
            unnamed = await client.post("/v1/desktop/sequence", json={"steps": []}, headers=auth_header(token))
            nobody = await client.post(
                "/v1/desktop/sequence", headers=auth_header(token),
                json={"require_active_title": "no-such-window-616", "steps": [{"do": "wait", "ms": 1}]})
            return anonymous.status, unnamed.status, nobody.status, await json_payload(nobody)

    anonymous, unnamed, nobody, answer = asyncio.run(go())
    assert anonymous in (401, 403)
    assert unnamed == 400
    # On Windows the guard refuses before any input; elsewhere there is no driver.
    assert nobody == (409 if sys.platform == "win32" else 501)
    assert answer["ok"] is False


def test_the_route_is_in_the_registry():
    assert ("POST", "/v1/desktop/sequence", "handle_v1_desktop_sequence", "desktop", None) in ROUTES


# ---------------------------------------------------------------------
# 5. the MCP tool
# ---------------------------------------------------------------------
def test_the_tool_is_listed_and_needs_approval():
    tool = next(tool for tool in MCP_TOOLS if tool["name"] == "desktop.sequence")
    assert tool["inputSchema"]["required"] == ["steps", "require_active_title"]
    assert classify_tool_risk("desktop.sequence") == "dangerous"


def test_the_tool_waits_as_long_as_the_sequence_takes(monkeypatch):
    seen = {}

    def bridge_call(ctx, path, payload, *, timeout):
        seen.update(path=path, payload=payload, timeout=timeout)
        return {"ok": True, "steps_done": 2}

    monkeypatch.setattr(tool_desktop_sequence, "_bridge_call", bridge_call)
    args = {"require_active_title": "game",
            "steps": [{"do": "key_down", "key": "w"}, {"do": "wait", "ms": 40_000}]}
    result = tool_desktop_sequence.handle_desktop_sequence_tool("desktop.sequence", args, ctx=None)
    assert seen["path"] == "/v1/desktop/sequence" and seen["payload"] is args
    assert seen["timeout"] == 55
    assert json.loads(result["content"][0]["text"]) == {"ok": True, "steps_done": 2}
    assert tool_desktop_sequence.handle_desktop_sequence_tool("desktop.key", {}, ctx=None) is None


@pytest.mark.parametrize("steps", [None, "x", [1, {"ms": "long"}, {"ms": 10**9}]])
def test_the_tool_s_timeout_survives_any_arguments(steps):
    assert 15 <= tool_desktop_sequence._timeout({"steps": steps}) <= 90


def test_the_tool_passes_a_refusal_on_in_the_bridge_s_own_words(monkeypatch):
    """Not "HTTP Error 409: Conflict": the agent has to learn which window was in front."""
    refusal = {"ok": False, "error": "input_guard_failed", "active_title": "Terminal", "steps_done": 0}

    def bridge_call(ctx, path, payload, *, timeout):
        raise urllib.error.HTTPError(path, 409, "Conflict", {}, io.BytesIO(json.dumps(refusal).encode()))

    monkeypatch.setattr(tool_desktop_sequence, "_bridge_call", bridge_call)
    result = tool_desktop_sequence.handle_desktop_sequence_tool(
        "desktop.sequence", {"steps": [], "require_active_title": "game"}, ctx=None)
    assert result["isError"] is True
    assert json.loads(result["content"][0]["text"]) == refusal


def test_a_refusal_that_is_not_json_still_says_what_happened(monkeypatch):
    def bridge_call(ctx, path, payload, *, timeout):
        raise urllib.error.HTTPError(path, 502, "Bad Gateway", {}, io.BytesIO(b"<html>upstream</html>"))

    monkeypatch.setattr(tool_desktop_sequence, "_bridge_call", bridge_call)
    result = tool_desktop_sequence.handle_desktop_sequence_tool("desktop.sequence", {}, ctx=None)
    answer = json.loads(result["content"][0]["text"])
    assert answer["error"] == "sequence failed with HTTP 502" and "upstream" in answer["detail"]


# ---------------------------------------------------------------------
# 6. desktop.mouse and `absolute: false` (#617)
# ---------------------------------------------------------------------
def test_xdotool_moves_by_a_delta_when_asked_to():
    """It used to send `mousemove -5 7`: a jump to a corner, reported as a relative move."""
    command, tool, error = build_mouse_command(env={"has_xdotool": True}, x=-5, y=7, absolute=False)
    assert error is None and tool == "xdotool"
    assert command.endswith("xdotool mousemove_relative -- -5 7")


def test_xdotool_still_moves_to_a_point_by_default():
    command, _, _ = build_mouse_command(env={"has_xdotool": True}, x=50, y=60)
    assert command.endswith("xdotool mousemove 50 60")


def test_the_description_no_longer_promises_more_than_the_tool_does():
    tool = next(tool for tool in MCP_TOOLS if tool["name"] == "desktop.mouse")
    assert "by (x, y) when `absolute` is false" in tool["description"]
