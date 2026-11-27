"""Timed input sequences: what a caller may ask for, and the runner (#616)."""
# `desktop.key` and `desktop.click` press and release in one call, and every
# call is a round trip. That leaves three things out of reach: holding a key or
# a button, moving the pointer by a delta, and timing two actions against each
# other ("hold jump, 280 ms later right-click"). A sequence is a list of steps
# the bridge runs on the host in one call.
#
# This module is the part that does not depend on a platform: it validates the
# steps before anything is pressed, and it runs them against a driver. Two
# properties are deliberate:
#
# * Nothing stays held. Whatever a sequence pressed is released when it ends,
#   however it ends -- finished, refused by the window guard, stopped by the
#   control lease, or broken by an exception. If the system refuses a release,
#   the result says which key or button is still down instead of reporting success.
# * The window is named. A sequence is refused unless the caller says which
#   foreground window it is meant for, and it stops the moment that window is
#   no longer in front. Held keys in the wrong window are how an agent types
#   into a terminal it never meant to touch.

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from typing import Any, NamedTuple, Protocol

MAX_STEPS = 200
#: The longest one key or button may stay down.
MAX_HOLD_MS = 15_000
#: The longest a whole sequence may run.
MAX_TOTAL_MS = 45_000
#: A wait is slept in slices so a stop request is noticed inside it.
_SLICE_MS = 50
_DEFAULT_PRESS_MS = 60
_BUTTONS = ("left", "right", "middle")
_MAX_DELTA = 100_000
_MAX_CLICKS = 100

__all__ = [
    "Clock", "Guard", "MAX_HOLD_MS", "MAX_STEPS", "MAX_TOTAL_MS",
    "InputDriver", "SequenceError", "plan_sequence", "planned_duration_ms", "run_sequence",
]


class SequenceError(ValueError):
    """A step the bridge will not run; `index` is the step's position."""

    def __init__(self, message: str, index: int | None = None) -> None:
        """Remember which step was refused, when it was one step."""
        super().__init__(message)
        self.index = index


class InputDriver(Protocol):
    """What a platform has to provide for a sequence to run on it."""

    def knows_key(self, name: str) -> bool:
        """Whether `name` is a key this platform can press."""

    def key_down(self, name: str) -> None:
        """Press a key and leave it down."""

    def key_up(self, name: str) -> None:
        """Release a key."""

    def button_down(self, name: str) -> None:
        """Press a mouse button and leave it down."""

    def button_up(self, name: str) -> None:
        """Release a mouse button."""

    def move_rel(self, dx: int, dy: int) -> None:
        """Move the pointer by a delta, as a device would."""

    def move_to(self, x: int, y: int) -> None:
        """Put the pointer at a desktop position."""

    def scroll(self, clicks: int) -> None:
        """Turn the wheel; positive is away from the user."""

    def foreground_title(self) -> str:
        """Title of the window that would receive the input now."""


class _Int(NamedTuple):
    """An integer field of a step: its name, its bounds, and its default if it has one."""

    field: str
    low: int
    high: int
    default: int | None = None


_WAIT_MS = _Int("ms", 0, MAX_TOTAL_MS)
_PRESS_MS = _Int("ms", 1, MAX_HOLD_MS, _DEFAULT_PRESS_MS)
_MOVE_MS = _Int("ms", 0, MAX_HOLD_MS, 0)
_DX = _Int("dx", -_MAX_DELTA, _MAX_DELTA, 0)
_DY = _Int("dy", -_MAX_DELTA, _MAX_DELTA, 0)
_X = _Int("x", -_MAX_DELTA, _MAX_DELTA)
_Y = _Int("y", -_MAX_DELTA, _MAX_DELTA)
_CLICKS = _Int("clicks", -_MAX_CLICKS, _MAX_CLICKS)


def _integer(step: dict[str, Any], index: int, spec: _Int) -> int:
    value = step.get(spec.field, spec.default)
    if isinstance(value, bool) or not isinstance(value, int):
        raise SequenceError(f"step {index}: '{spec.field}' must be an integer", index)
    if not spec.low <= value <= spec.high:
        raise SequenceError(f"step {index}: '{spec.field}' must be between {spec.low} and {spec.high}", index)
    return value


def _key_name(step: dict[str, Any], index: int, driver: InputDriver) -> str:
    name = step.get("key")
    if not isinstance(name, str) or not name.strip():
        raise SequenceError(f"step {index}: 'key' must be a key name", index)
    name = name.strip().lower()
    if not driver.knows_key(name):
        raise SequenceError(f"step {index}: unknown key {name!r}", index)
    return name


def _button_name(step: dict[str, Any], index: int) -> str:
    name = step.get("button", "left")
    if name not in _BUTTONS:
        raise SequenceError(f"step {index}: 'button' must be one of {', '.join(_BUTTONS)}", index)
    return name


def _plan_wait(step, index, _driver):
    return {"do": "wait", "ms": _integer(step, index, _WAIT_MS)}


def _plan_key(step, index, driver):
    return {"do": step["do"], "key": _key_name(step, index, driver)}


def _plan_tap(step, index, driver):
    return {"do": "tap", "key": _key_name(step, index, driver), "ms": _integer(step, index, _PRESS_MS)}


def _plan_button(step, index, _driver):
    return {"do": step["do"], "button": _button_name(step, index)}


def _plan_click(step, index, _driver):
    return {"do": "click", "button": _button_name(step, index), "ms": _integer(step, index, _PRESS_MS)}


def _plan_move(step, index, _driver):
    return {"do": "move", "dx": _integer(step, index, _DX), "dy": _integer(step, index, _DY),
            "ms": _integer(step, index, _MOVE_MS)}


def _plan_move_to(step, index, _driver):
    return {"do": "move_to", "x": _integer(step, index, _X), "y": _integer(step, index, _Y)}


def _plan_scroll(step, index, _driver):
    return {"do": "scroll", "clicks": _integer(step, index, _CLICKS)}


_PLANNERS: dict[str, Callable[[dict[str, Any], int, InputDriver], dict[str, Any]]] = {
    "wait": _plan_wait,
    "key_down": _plan_key,
    "key_up": _plan_key,
    "tap": _plan_tap,
    "mouse_down": _plan_button,
    "mouse_up": _plan_button,
    "click": _plan_click,
    "move": _plan_move,
    "move_to": _plan_move_to,
    "scroll": _plan_scroll,
}


def _step_ms(step: dict[str, Any]) -> int:
    return int(step.get("ms", 0))


def planned_duration_ms(steps: list[dict[str, Any]]) -> int:
    """How long the steps take if nothing stops them."""
    return sum(_step_ms(step) for step in steps)


def _held_name(step: dict[str, Any]) -> str:
    return "key:" + step["key"] if "key" in step else "button:" + step["button"]


def _note_press_or_release(down_since: dict[str, int], step: dict[str, Any], now: int) -> None:
    if step["do"] in ("key_down", "mouse_down"):
        down_since.setdefault(_held_name(step), now)
    elif step["do"] in ("key_up", "mouse_up"):
        down_since.pop(_held_name(step), None)


def _held_too_long(down_since: dict[str, int], now: int) -> str | None:
    return next((name for name, since in down_since.items() if now - since > MAX_HOLD_MS), None)


def _check_holds(steps: list[dict[str, Any]]) -> None:
    """Refuse a plan that keeps one key or button down past MAX_HOLD_MS."""
    down_since: dict[str, int] = {}
    now = 0
    for index, step in enumerate(steps):
        _note_press_or_release(down_since, step, now)
        now += _step_ms(step)
        name = _held_too_long(down_since, now)
        if name:
            raise SequenceError(f"step {index}: {name} would stay down longer than {MAX_HOLD_MS} ms", index)


def _check_shape(raw_steps: Any) -> None:
    if not isinstance(raw_steps, list) or not raw_steps:
        raise SequenceError("'steps' must be a non-empty list")
    if len(raw_steps) > MAX_STEPS:
        raise SequenceError(f"'steps' may hold at most {MAX_STEPS} steps")


def _plan_step(raw: Any, index: int, driver: InputDriver) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SequenceError(f"step {index}: must be an object", index)
    planner = _PLANNERS.get(str(raw.get("do")))
    if planner is None:
        raise SequenceError(f"step {index}: 'do' must be one of {', '.join(_PLANNERS)}", index)
    return planner(raw, index, driver)


def plan_sequence(raw_steps: Any, driver: InputDriver) -> list[dict[str, Any]]:
    """Validate the caller's steps; raises SequenceError before anything is pressed."""
    _check_shape(raw_steps)
    steps = [_plan_step(raw, index, driver) for index, raw in enumerate(raw_steps)]
    total = planned_duration_ms(steps)
    if total > MAX_TOTAL_MS:
        raise SequenceError(f"the sequence would run {total} ms; the limit is {MAX_TOTAL_MS} ms")
    _check_holds(steps)
    return steps


class Guard(NamedTuple):
    """What may stop a run: the window it is for, and the control lease's verdict."""

    title: str
    should_stop: Callable[[], Any] | None = None


class Clock(NamedTuple):
    """Time as the runner sees it; tests pass a virtual one."""

    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], float] = time.monotonic


class _Stopped(Exception):
    """Raised inside the runner to unwind to the release-everything block."""

    def __init__(self, reason: dict[str, Any]) -> None:
        """Carry the reason, which becomes the body of the answer."""
        super().__init__(reason.get("error", "stopped"))
        self.reason = reason


class _Run:
    """One execution: remembers what is down so it can always be let go."""

    def __init__(self, driver: InputDriver, guard: Guard, clock: Clock) -> None:
        """Start with nothing held."""
        self.driver = driver
        self.required_title = guard.title.lower()
        self.should_stop = guard.should_stop
        self.clock = clock
        self.keys: list[str] = []
        self.buttons: list[str] = []

    def check(self) -> None:
        """Stop if the control lease refuses or another window came to the front."""
        blocked = self.should_stop() if self.should_stop else None
        if blocked:
            raise _Stopped({key: value for key, value in dict(blocked).items() if key != "ok"})
        title = self.driver.foreground_title()
        if self.required_title not in title.lower():
            raise _Stopped({
                "error": "input_guard_failed",
                "message": "Active window does not match required title",
                "active_title": title,
            })

    def wait(self, ms: int) -> None:
        deadline = self.clock.now() + ms / 1000.0
        while True:
            left = deadline - self.clock.now()
            if left <= 0:
                return
            self.clock.sleep(min(left, _SLICE_MS / 1000.0))
            self.check()

    def key_down(self, name: str) -> None:
        self.driver.key_down(name)
        if name not in self.keys:
            self.keys.append(name)

    def key_up(self, name: str) -> None:
        self.driver.key_up(name)
        if name in self.keys:
            self.keys.remove(name)

    def button_down(self, name: str) -> None:
        self.driver.button_down(name)
        if name not in self.buttons:
            self.buttons.append(name)

    def button_up(self, name: str) -> None:
        self.driver.button_up(name)
        if name in self.buttons:
            self.buttons.remove(name)

    def move(self, dx: int, dy: int, ms: int) -> None:
        """Send the delta at once, or spread over `ms` so the counts add up exactly."""
        parts = max(1, min(200, ms // 8))
        sent_x = sent_y = 0
        for part in range(1, parts + 1):
            want_x, want_y = round(dx * part / parts), round(dy * part / parts)
            if (want_x, want_y) != (sent_x, sent_y):
                self.driver.move_rel(want_x - sent_x, want_y - sent_y)
                sent_x, sent_y = want_x, want_y
            if ms:
                self.wait(ms // parts)

    def release_all(self) -> tuple[dict[str, list[str]], list[str]]:
        """Let go of everything still down; returns what was released and what refused to be."""
        released: dict[str, list[str]] = {"keys": [], "buttons": []}
        stuck: list[str] = []
        pending = [("buttons", "button:", self.driver.button_up, name) for name in reversed(self.buttons)]
        pending += [("keys", "key:", self.driver.key_up, name) for name in reversed(self.keys)]
        for kind, prefix, release, name in pending:
            if _released(release, name):
                released[kind].append(name)
            else:
                stuck.append(prefix + name)
        self.keys.clear()
        self.buttons.clear()
        return released, stuck


def _released(action: Callable[[str], None], name: str) -> bool:
    """Try one release; whatever goes wrong, the releases after it still have to happen."""
    with contextlib.suppress(Exception):
        action(name)
        return True
    return False


def _do_tap(run: _Run, step: dict[str, Any]) -> None:
    run.key_down(step["key"])
    run.wait(step["ms"])
    run.key_up(step["key"])


def _do_click(run: _Run, step: dict[str, Any]) -> None:
    run.button_down(step["button"])
    run.wait(step["ms"])
    run.button_up(step["button"])


def _do_wait(run: _Run, step: dict[str, Any]) -> None:
    run.wait(step["ms"])


def _do_key_down(run: _Run, step: dict[str, Any]) -> None:
    run.key_down(step["key"])


def _do_key_up(run: _Run, step: dict[str, Any]) -> None:
    run.key_up(step["key"])


def _do_mouse_down(run: _Run, step: dict[str, Any]) -> None:
    run.button_down(step["button"])


def _do_mouse_up(run: _Run, step: dict[str, Any]) -> None:
    run.button_up(step["button"])


def _do_move(run: _Run, step: dict[str, Any]) -> None:
    run.move(step["dx"], step["dy"], step["ms"])


def _do_move_to(run: _Run, step: dict[str, Any]) -> None:
    run.driver.move_to(step["x"], step["y"])


def _do_scroll(run: _Run, step: dict[str, Any]) -> None:
    run.driver.scroll(step["clicks"])


_ACTIONS: dict[str, Callable[[_Run, dict[str, Any]], None]] = {
    "wait": _do_wait,
    "key_down": _do_key_down,
    "key_up": _do_key_up,
    "tap": _do_tap,
    "mouse_down": _do_mouse_down,
    "mouse_up": _do_mouse_up,
    "click": _do_click,
    "move": _do_move,
    "move_to": _do_move_to,
    "scroll": _do_scroll,
}


def run_sequence(steps: list[dict[str, Any]], driver: InputDriver, guard: Guard, clock: Clock = Clock()) -> dict[str, Any]:
    """Run planned steps; whatever happens, nothing is left held down."""
    run = _Run(driver, guard, clock)
    started = clock.now()
    done = 0
    result: dict[str, Any] = {"ok": True}
    try:
        for step in steps:
            run.check()
            _ACTIONS[step["do"]](run, step)
            done += 1
    except _Stopped as stop:
        result = {"ok": False, **stop.reason}
    except OSError as exc:
        result = {"ok": False, "error": "input_failed", "message": str(exc)}
    finally:
        released, stuck = run.release_all()
    if stuck:
        # Say so: a key the system would not release is still down for the user.
        result = {**result, "ok": False, "release_failed": stuck}
        result.setdefault("error", "input_failed")
        result.setdefault("message", "could not release: " + ", ".join(stuck))
    result.update({
        "steps_done": done,
        "steps_total": len(steps),
        "elapsed_ms": round((clock.now() - started) * 1000),
        "released_at_end": released,
    })
    return result
