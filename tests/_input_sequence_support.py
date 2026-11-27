"""Stand-ins shared by the input sequence tests (#616, #617): nothing here sends real input."""
from __future__ import annotations

import asyncio
import ctypes
import json
from types import SimpleNamespace

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from arena.desktop import input_sequence_handler
from arena.desktop.backends import windows_input
from arena.desktop.input_sequence import (
    Clock as RunnerClock,
    Guard,
    plan_sequence,
    run_sequence,
)

TITLE = "Game"


class Recorder:
    """An input driver that writes down what it was asked to do."""

    def __init__(self, title: str = "My Game Window") -> None:
        """Start with a window title that matches the guard used below."""
        self.events: list[tuple] = []
        self.title = title
        self.fail_on: str | None = None

    def _note(self, *event) -> None:
        if self.fail_on == event[0]:
            raise OSError("SendInput delivered 0 of 1 events")
        self.events.append(event)

    def knows_key(self, name: str) -> bool:
        return name in {"w", "space", "shift", "f3", "esc"}

    def key_down(self, name: str) -> None:
        self._note("key_down", name)

    def key_up(self, name: str) -> None:
        self._note("key_up", name)

    def button_down(self, name: str) -> None:
        self._note("button_down", name)

    def button_up(self, name: str) -> None:
        self._note("button_up", name)

    def move_rel(self, dx: int, dy: int) -> None:
        self._note("move_rel", dx, dy)

    def move_to(self, x: int, y: int) -> None:
        self._note("move_to", x, y)

    def scroll(self, clicks: int) -> None:
        self._note("scroll", clicks)

    def foreground_title(self) -> str:
        return self.title


class Clock:
    """Virtual time: sleeping advances it, so no test waits for real."""

    def __init__(self) -> None:
        """Start at zero with nothing watching the sleeps."""
        self.now = 0.0
        self.on_sleep = None

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        if self.on_sleep:
            self.on_sleep(self.now)

    def as_runner_clock(self) -> RunnerClock:
        return RunnerClock(self.sleep, self.time)


def run(steps, driver=None, *, clock=None, guard=Guard(TITLE)):
    driver = driver or Recorder()
    clock = clock or Clock()
    result = run_sequence(plan_sequence(steps, driver), driver, guard, clock.as_runner_clock())
    return result, driver, clock


def _expect(holds: bool, otherwise: str) -> None:
    """Fail the test that got the stand-in called the wrong way."""
    if not holds:
        raise AssertionError(otherwise)


class FakeUser32:
    def __init__(self) -> None:
        """Deliver every event until a test says otherwise."""
        self.sent: list[windows_input.INPUT] = []
        self.cursor: tuple[int, int] | None = None
        self.deliver = 1
        self.cursor_is_readable = 1
        self.cursor_can_be_set = 1

    def SendInput(self, count, pointer, size):  # noqa: N802 -- the Win32 name
        _expect(count == 1, f"SendInput was given {count} events at once")
        _expect(size == ctypes.sizeof(windows_input.INPUT), f"SendInput was told an INPUT is {size} bytes")
        self.sent.append(pointer._obj)
        return self.deliver

    def MapVirtualKeyW(self, vk, kind):  # noqa: N802
        _expect(kind == 0, f"MapVirtualKeyW was asked for mapping {kind}, not virtual key to scan code")
        return 0x100 + vk

    def SetCursorPos(self, x, y):  # noqa: N802
        if self.cursor_can_be_set:
            self.cursor = (x, y)
        return self.cursor_can_be_set

    def GetCursorPos(self, pointer):  # noqa: N802
        if self.cursor_is_readable:
            pointer._obj.x, pointer._obj.y = self.cursor
        return self.cursor_is_readable

    def GetForegroundWindow(self):  # noqa: N802
        return 42

    def GetWindowTextW(self, hwnd, buffer, size):  # noqa: N802
        _expect(hwnd == 42, f"GetWindowTextW was asked about window {hwnd}, not the foreground one")
        buffer.value = "Abyssal Ascent - Minecraft"[: size - 1]


def handler_ctx(*, env=None, control=lambda: None):
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


def post_raw(ctx, body):
    """Status and text, for answers that are not the handler's own JSON."""
    async def go():
        app = web.Application()
        app.router.add_post("/v1/desktop/sequence", input_sequence_handler.make_desktop_sequence_handler(ctx))
        async with TestClient(TestServer(app)) as client:
            response = await client.post("/v1/desktop/sequence", json=body)
            return response.status, await response.text()

    return asyncio.run(go())


def post(ctx, body):
    status, text = post_raw(ctx, body)
    return status, json.loads(text)
